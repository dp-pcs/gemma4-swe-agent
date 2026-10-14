#!/usr/bin/env python3
"""Run frozen paired Gemma evaluation, gated by all-task grading controls."""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
import logging
import platform
import re
import signal
import subprocess
import sys
import time
import traceback
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from adk_eval_core.tracing import SessionTrace
from adk_submission import discover_adapters
from swegemma import EvalConfig, Evaluator
from swegemma.deduplication import resolve_task_snapshot_paths
from swegemma.harness.verification import verify_task
from swegemma.models import TaskResult, load_tasks
from swegemma.models.registry import setup_gemma_model_registry
from swegemma.results import append_task_result
from swegemma.sandbox.docker import ContainerManager

EXPECTED_HASHES = {
    "baseline": "75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142",
    "candidate": "dea621d29b9773e1c5e99098c1fb278283beabf04ed14e6adc8e6a1d43214719",
}
EXPECTED_VERSIONS = {"swegemma": "0.2.7", "adk-submission": "0.2.12", "adk-eval-core": "0.1.0"}
BUDGET = {"timeout_seconds": 90, "max_tool_calls": 40, "max_time_minutes": 4, "max_turns": 100}
PACKAGES = {
    "requests": ["requests", "requests.sessions"],
    "fastapi": ["fastapi", "fastapi.routing"],
    "rich": ["rich", "rich.prompt"],
    "httpx": ["httpx", "httpx._client"],
}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, default=str) + "\n")
    temporary.replace(path)


def json_safe(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return json_safe(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def provenance(output: str, repo: str) -> list[dict]:
    package = repo.rsplit("/", 1)[-1].lower()
    if package not in PACKAGES:
        raise ValueError(f"Unsupported provenance repository {repo}")
    records = []
    for line in output.splitlines():
        marker = "IMPORT_PROVENANCE "
        if marker in line:
            records.append(json.loads(line.split(marker, 1)[1].strip()))
    if len(records) < 2 or "IMPORT_PROVENANCE_REJECTED" in output:
        raise ValueError("Missing session-start/collection-finish snapshot import provenance")
    for record in records:
        for module in PACKAGES[package]:
            origin = PurePosixPath(record.get(module, ""))
            roots = [PurePosixPath("/workspace") / package, PurePosixPath("/workspace/src") / package]
            if ".." in origin.parts or not any(origin.is_relative_to(root) for root in roots):
                raise ValueError(f"Non-snapshot import {module}: {origin}")
    return records


class OfflineTimeoutContainerManager(ContainerManager):
    """Keep network=none; discard only the existing timeout fixture's TCP traffic."""

    def start(self) -> str:
        if self.config.network_mode != "none" or self.config.reuse_containers:
            raise ValueError("Timeout sink requires isolated, non-reused containers")
        container_id = super().start()
        container = self.client.containers.get(container_id)
        container.reload()
        namespace = ["sudo", "-n", "nsenter", "--target", str(container.attrs["State"]["Pid"]), "--net", "ip"]
        for arguments in [
            ["link", "add", "timeout-sink", "type", "dummy"],
            ["address", "add", "10.255.255.2/32", "dev", "timeout-sink"],
            ["link", "set", "timeout-sink", "up"],
            ["route", "add", "10.255.255.1/32", "dev", "timeout-sink", "src", "10.255.255.2"],
        ]:
            subprocess.run(namespace + arguments, check=True, capture_output=True, text=True)
        return container_id


class PairedEvaluator(Evaluator):
    """Keep agent errors even if installed verification discards them on passing tests."""
    async def _run_agent_sandbox(self, *args, **kwargs):
        result = await super()._run_agent_sandbox(*args, **kwargs)
        self.last_agent_error = result[1]
        return result


def persist(result, directory: Path, running: list, extra: dict | None = None) -> dict:
    raw_status = result.status
    result.status = (
        "SUCCESS" if result.resolved else
        "TIMEOUT" if re.search(r"timeout|timed out", result.error or "", re.IGNORECASE) else
        "ERROR" if result.error else "FAILED"
    )
    running.append(result)
    append_task_result(result, directory, running)
    # Explicit empty artifacts distinguish no patch/no grading from missing files.
    for subdir, suffix, text in [("patches", ".patch", result.agent_patch), ("test_outputs", ".log", result.test_output)]:
        target = directory / subdir / (result.instance_id.replace("/", "__") + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text or "")
    record = json_safe(result.model_dump(exclude={"trace"}))
    record.update({
        "instance_id": result.instance_id,
        "error": result.error,
        "trace_json_path": result.trace_json_path,
        "total_llm_calls": result.total_llm_calls,
    })
    record["raw_harness_status"] = raw_status
    record.update(extra or {})
    record["patch_bytes"] = len((result.agent_patch or "").encode())
    save(directory / "records" / (result.instance_id + ".json"), record)
    return record


def summarize(task_ids: list[str], held_out: list[str], diagnostics: list[str], results: dict, status: str, controls_trusted: bool) -> dict:
    pairs = []
    for task in task_ids:
        arms = {arm: results[arm].get(task) for arm in results}
        complete = all(arms.values())
        outcome = "incomplete"
        if complete:
            b, c = arms["baseline"]["resolved"], arms["candidate"]["resolved"]
            outcome = "gain" if c and not b else "regression" if b and not c else "unchanged_success" if b else "unchanged_failure"
        pairs.append({"instance_id": task, "split": "held_out" if task in held_out else "diagnostic", "outcome": outcome, "arms": arms})
    aggregates = {}
    for split, ids in [("held_out", held_out), ("diagnostic", diagnostics)]:
        selected = [pair for pair in pairs if pair["instance_id"] in ids]
        aggregates[split] = {
            "expected_tasks_per_arm": len(ids),
            "paired_completed": sum(p["outcome"] != "incomplete" for p in selected),
            "paired_outcomes": {k: sum(p["outcome"] == k for p in selected) for k in ["gain", "regression", "unchanged_success", "unchanged_failure", "incomplete"]},
            "arms": {},
        }
        for arm in results:
            rows = [results[arm][task] for task in ids if task in results[arm]]
            aggregates[split]["arms"][arm] = {
                "completed": len(rows), "resolved": sum(row["resolved"] for row in rows),
                "duration_seconds": sum(row["duration_seconds"] for row in rows),
                "tool_calls": sum(row["tool_calls"] for row in rows),
                "llm_calls": sum(row["total_llm_calls"] for row in rows),
                "errors": sum(bool(row["error"]) for row in rows),
                "resolution_rate": sum(row["resolved"] for row in rows) / len(ids) if len(rows) == len(ids) else None,
            }
    return {"status": status, "controls_trusted": controls_trusted, "aggregates": aggregates, "taskwise_pairs": pairs,
            "interpretation": "One sample per arm/task. Held-out and diagnostic results are separate; incomplete arms are not gains. Resolution follows the real grader for non-empty patches with valid snapshot provenance, even when an agent timeout leaves a salvageable passing patch. Agent completion/errors are separate diagnostics, not grading outcomes. Empty-patch or untrusted-provenance runs cannot resolve. No statistical or promotion claim; recovery-loop evidence requires trace analysis."}


async def main(args: argparse.Namespace) -> None:
    import yaml

    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    # Never overwrite a previous invocation, including interrupted artifacts.
    if (output / "metadata.json").exists():
        output = output / "invocations" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output.mkdir(parents=True, exist_ok=False)
    save(args.output / "latest_invocation.json", {"output": str(output)})
    handler = logging.FileHandler(output / "runner.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    start = time.perf_counter()
    metadata = {"status": "initializing", "started_utc": utc(), "arguments": vars(args), "output": str(output),
                "python": sys.version, "platform": platform.platform(), "runner_sha256": sha256(Path(__file__)),
                "design": "All-nine unpatched/reference controls before inference; taskwise alternating arm order; same image/server/sampling, concurrency one."}
    evaluators, results = {}, {"baseline": {}, "candidate": {}}
    controls, ids, held_out, diagnostics = [], [], [], []
    trusted = False
    status = "interrupted"
    save(output / "metadata.json", metadata)
    try:
        plan_path = Path(__file__).with_name("evaluation_plan.json")
        plan = json.loads(plan_path.read_text())
        save(output / "evaluation_plan.json", plan)
        held_out, diagnostics = plan["held_out_task_ids"], plan["diagnostic_task_ids"]
        ids = held_out + diagnostics
        if len(held_out) != 7 or len(diagnostics) != 2 or len(set(ids)) != 9 or plan["tasks_per_configuration"] != 9 or plan["budgets"] != BUDGET:
            raise ValueError("Unexpected frozen task selection/budgets")
        metadata.update({"evaluation_plan_sha256": sha256(plan_path), "task_ids": ids, "budget": BUDGET})
        versions = {name: importlib.metadata.version(name) for name in EXPECTED_VERSIONS}
        if versions != EXPECTED_VERSIONS:
            raise ValueError(f"Unexpected installed evaluation runtime: {versions}")
        metadata["versions"] = versions
        archives = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
        members, all_members = {}, {}
        for arm, archive in archives.items():
            actual = sha256(archive)
            if actual != EXPECTED_HASHES[arm]:
                raise ValueError(f"Unexpected {arm} ZIP hash: {actual}")
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                if len(names) != len(set(names)):
                    raise ValueError("Duplicate ZIP members")
                for name in names:
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts or (z.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError(f"Unsafe ZIP member {name}")
                all_members[arm] = sorted(names)
                members[arm] = {name: z.read(name) for name in names if not name.endswith("/")}
        if all_members["baseline"] != all_members["candidate"]:
            raise ValueError("Candidate changed complete ZIP member set")
        changed = sorted(name for name in members["baseline"] if members["baseline"][name] != members["candidate"][name])
        if changed != ["prompts/system.md"]:
            raise ValueError(f"Unexpected candidate changes: {changed}")
        configs = {arm: yaml.safe_load(files["eval_config.yaml"]) for arm, files in members.items()}
        if any(config["evaluation"] != BUDGET for config in configs.values()):
            raise ValueError("Archive evaluation budget mismatch")
        metadata.update({"archive_paths": archives, "archive_sha256": EXPECTED_HASHES, "archive_members": all_members,
                         "member_sha256": {arm: {name: hashlib.sha256(content).hexdigest() for name, content in files.items()} for arm, files in members.items()},
                         "changed_files": changed, "submission_configs": configs})
        data = args.data_root.resolve()
        task_file = data / "tasks.jsonl"
        if sha256(task_file) != plan["task_file_sha256"]:
            raise ValueError("Task corpus differs from frozen selection")
        tasks = {task.instance_id: task for task in load_tasks(task_file) if task.instance_id in ids}
        if set(tasks) != set(ids):
            raise ValueError("Selected tasks missing")
        snapshots = {}
        for task in tasks.values():
            paths = resolve_task_snapshot_paths(data / "snapshots", task.instance_id, task.repo)
            snapshots[task.instance_id] = [{"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size} if p else None for p in paths]
        image = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image], text=True))
        if "PYTEST_PLUGINS=container_provenance" not in image[0]["Config"]["Env"]:
            raise ValueError("Image lacks container_provenance plugin")
        # Pin the inspected image ID, not a tag that could change between arms.
        image_id = image[0]["Id"]
        with urllib.request.urlopen(args.api_base.rstrip("/") + "/models", timeout=10) as response:
            served = json.load(response)
        if not {"main_lora", "tool_lora"}.issubset({m["id"] for m in served["data"]}):
            raise ValueError("Server does not serve both frozen adapters")
        metadata.update({"tasks_sha256": sha256(task_file), "snapshot_metadata": snapshots, "image_inspect": image,
                         "served_models": served, "api_base": args.api_base,
                         "data_artifacts": {
                             name: {"root": str(data), "path": str(data / name), "exists": (data / name).exists(),
                                    "is_directory": (data / name).is_dir(), "byte_identity_verified": False}
                             for name in ["wheels", "graphs", "embeddings"]
                         },
                         "data_identity_scope": "Both arms use the same data-root paths. Selected snapshot bytes and task corpus are hashed; wheel/graph/embedding trees are not recursively hashed."})
        metadata["installed_distributions"] = sorted(
            [{"name": dist.metadata["Name"], "version": dist.version} for dist in importlib.metadata.distributions()],
            key=lambda item: (item["name"] or "").lower(),
        )
        metadata["server_runtime"] = {}
        server_root = args.api_base.rstrip("/").removesuffix("/v1")
        for endpoint in ["/version", "/server_info"]:
            try:
                with urllib.request.urlopen(server_root + endpoint, timeout=10) as response:
                    body = response.read().decode()
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    pass
                metadata["server_runtime"][endpoint] = body
            except Exception as exc:
                metadata["server_runtime"][endpoint] = {"unavailable": str(exc)}
        server_version = metadata["server_runtime"]["/version"]
        if not isinstance(server_version, dict) or server_version.get("version") != "0.29.0":
            raise ValueError(f"Unexpected or unverifiable remote vLLM version: {server_version}")
        metadata["submission_yaml_text"] = {
            arm: {name: content.decode("utf-8") for name, content in files.items() if name.endswith((".yaml", ".yml"))}
            for arm, files in members.items()
        }
        for arm, archive in archives.items():
            source = output / "sources" / arm
            with zipfile.ZipFile(archive) as z:
                z.extractall(source)
            adapters = discover_adapters(source)
            models = setup_gemma_model_registry(api_base=args.api_base, api_key="EMPTY", adapter_manifest=adapters)
            config = EvalConfig(tasks_path=task_file, snapshots_dir=data / "snapshots", wheels_dir=data / "wheels",
                                graph_dir=str(data / "graphs"), embeddings_dir=str(data / "embeddings"), submission_dir=source,
                                results_dir=output / arm, models=models, adapter_manifest=adapters, image=image_id, sandbox="docker",
                                task_ids=ids, concurrency=1, display_mode="quiet", **BUDGET)
            evaluators[arm] = PairedEvaluator(config)
            evaluators[arm].sandbox = evaluators[arm].docker = OfflineTimeoutContainerManager(evaluators[arm].docker.config)
            metadata.setdefault("runtime_configs", {})[arm] = {field.name: json_safe(getattr(config, field.name)) for field in dataclasses.fields(config)}
        metadata["offline_network"] = {
            "network_mode": "none", "timeout_sink": "10.255.255.1/32",
            "mechanism": "Host-injected dummy NIC in each private namespace; no default route, veth or agent NET_ADMIN",
            "scope": "Local verifier compatibility for existing Requests TCP timeout fixtures; not scorer-network parity",
        }
        metadata["status"] = "controls"
        save(output / "metadata.json", metadata)
        evaluator = evaluators["baseline"]
        control_running = {"unpatched": [], "reference": []}
        for index, task_id in enumerate(ids, 1):
            task = evaluator._hydrate_task_from_secret(tasks[task_id])
            if not task.patch.strip():
                raise ValueError(f"Missing real reference patch for {task_id}")
            snapshot, base, snapshot_patch = resolve_task_snapshot_paths(evaluator.config.snapshots_dir, task_id, task.repo)
            for kind, patch in [("unpatched", ""), ("reference", task.patch)]:
                directory = output / "controls" / kind
                config = dataclasses.replace(evaluator.config, results_dir=directory)
                control_start = time.perf_counter()
                try:
                    result = await verify_task(evaluator.docker, config, task, snapshot, base_snapshot_path=base,
                                               patch_path=snapshot_patch, agent_patch=patch, agent_error=None,
                                               trace=SessionTrace(), start_time=control_start)
                    origins = provenance(result.test_output, task.repo)
                    valid = (not result.resolved and result.test_exit_code == 1 and not result.error) if kind == "unpatched" else (result.resolved and result.test_exit_code == 0 and not result.error)
                    # An unpatched failure must be an actual assertion failure, not a collection/setup failure.
                    if kind == "unpatched":
                        valid = valid and bool(re.search(r"\b[1-9][0-9]* failed\b", result.test_output)) and not re.search(r"\b[1-9][0-9]* errors?\b", result.test_output)
                    reason = None if valid else "Control did not produce expected real test outcome"
                except Exception:
                    reason = traceback.format_exc()
                    origins, valid = [], False
                    if "result" not in locals() or result.instance_id != task_id:
                        result = TaskResult(instance_id=task_id, repo=task.repo, resolved=False, agent_patch=patch,
                                            test_output="", test_exit_code=-1, duration_seconds=time.perf_counter() - control_start, error=reason)
                record = persist(result, directory, control_running[kind], {"kind": kind, "trusted": valid, "trust_error": reason, "import_provenance": origins})
                controls.append(record)
                save(output / "controls_summary.json", controls)
                evaluator.docker.cleanup_all()
                print(f"CONTROL {kind} {task_id}: trusted={valid} resolved={result.resolved}", flush=True)
                del result
        trusted = len(controls) == 18 and all(c["trusted"] for c in controls)
        if not trusted:
            raise RuntimeError("Untrusted grading controls; model evaluation prohibited (see controls_summary.json)")
        metadata["status"] = "evaluating"
        metadata["controls_trusted"] = True
        metadata["evaluation_order"] = [{"task_id": task, "arms": ["baseline", "candidate"] if index % 2 == 0 else ["candidate", "baseline"]} for index, task in enumerate(ids)]
        save(output / "metadata.json", metadata)
        running = {"baseline": [], "candidate": []}
        for index, entry in enumerate(metadata["evaluation_order"], 1):
            task_id = entry["task_id"]
            for arm in entry["arms"]:
                evaluator = evaluators[arm]
                evaluator.last_agent_error = None
                task_start = time.perf_counter()
                log = logging.FileHandler(output / f"{arm}-{task_id}.log")
                log.setFormatter(handler.formatter)
                logging.getLogger().addHandler(log)
                try:
                    print(f"START {arm} {task_id}", flush=True)
                    result = await evaluator.evaluate_task(tasks[task_id], task_index=index, total_tasks=len(ids))
                    raw_resolved = result.resolved
                    errors = []
                    if not result.agent_patch.strip():
                        errors.append("No emitted agent patch; not a successful model resolution")
                    origins = []
                    if result.test_output:
                        try:
                            origins = provenance(result.test_output, result.repo)
                        except Exception as exc:
                            errors.append(str(exc))
                    elif result.resolved:
                        errors.append("Missing grading output/provenance")
                    if errors:
                        result.resolved = False
                        result.error = "\n".join(filter(None, [result.error, *errors]))
                    record = persist(result, output / arm, running[arm], {
                        "raw_harness_resolved": raw_resolved,
                        "agent_error": evaluator.last_agent_error,
                        "agent_completed_without_error": not bool(evaluator.last_agent_error),
                        "import_provenance": origins,
                    })
                except Exception:
                    error = traceback.format_exc()
                    result = TaskResult(instance_id=task_id, repo=tasks[task_id].repo, resolved=False, agent_patch="", test_output="",
                                        test_exit_code=-1, duration_seconds=time.perf_counter() - task_start, error=error)
                    record = persist(result, output / arm, running[arm], {"exception": error})
                finally:
                    logging.getLogger().removeHandler(log)
                    log.close()
                    evaluator.docker.cleanup_all()
                results[arm][task_id] = record
                save(output / "comparison_summary.json", summarize(ids, held_out, diagnostics, results, "running", trusted))
                print(f"COMPLETE {arm} {task_id}: resolved={record['resolved']} error={record['error']}", flush=True)
        status = "complete"
    except BaseException:
        metadata["error"] = traceback.format_exc()
        logging.exception("Comparison interrupted")
        raise
    finally:
        cleanup_errors = []
        for arm, evaluator in evaluators.items():
            try:
                evaluator.docker.cleanup_all()
            except Exception:
                cleanup_errors.append({"arm": arm, "error": traceback.format_exc()})
        metadata.update({"status": status, "finished_utc": utc(), "duration_seconds": time.perf_counter() - start,
                         "controls_trusted": trusted, "cleanup_errors": cleanup_errors})
        save(output / "comparison_summary.json", summarize(ids, held_out, diagnostics, results, status, trusted))
        metadata["artifact_manifest"] = [{"path": str(p.relative_to(output)), "bytes": p.stat().st_size, "sha256": sha256(p)}
                                         for p in sorted(output.rglob("*")) if p.is_file() and p.name not in {"metadata.json", "runner.log"}]
        save(output / "metadata.json", metadata)
        logging.getLogger().removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/v1")
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    asyncio.run(main(parser.parse_args()))
