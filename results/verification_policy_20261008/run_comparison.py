#!/usr/bin/env python3
"""Run the frozen baseline and verification-policy candidate with real Gemma inference."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import time
import subprocess
import urllib.request
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from adk_eval_core.tracing import SessionTrace
from adk_submission import discover_adapters
from swegemma import EvalConfig, Evaluator
from swegemma.models.registry import setup_gemma_model_registry
from swegemma.deduplication import resolve_task_snapshot_paths
from swegemma.harness.verification import verify_task
from swegemma.models import load_tasks
from swegemma.results import append_task_result

TASK_IDS = ["requests_7315", "requests_7309", "requests_7427", "fastapi_14258", "rich_3052"]
EXPECTED_HASHES = {
    "baseline": "75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142",
    "candidate": "5b75192b9f11469eaf73fad209cdf30b48ce9605264db87b3cc2b6d09d4f6064",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n")


async def main(args: argparse.Namespace) -> None:
    import yaml

    archives = {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}
    members = {}
    for label, archive in archives.items():
        if sha256(archive) != EXPECTED_HASHES[label]:
            raise ValueError(f"Unexpected {label} archive bytes: {archive}")
        with zipfile.ZipFile(archive) as z:
            members[label] = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    if members["baseline"].keys() != members["candidate"].keys():
        raise ValueError("Candidate changed archive members")
    changed = [n for n in members["baseline"] if members["baseline"][n] != members["candidate"][n]]
    if changed != ["prompts/system.md"]:
        raise ValueError(f"Unexpected candidate changes: {changed}")
    budget = yaml.safe_load(members["baseline"]["eval_config.yaml"])["evaluation"]
    if budget != {"timeout_seconds": 90, "max_tool_calls": 40, "max_time_minutes": 4, "max_turns": 100}:
        raise ValueError(f"Unexpected baseline budget: {budget}")

    data = args.data_root.resolve()
    task_file = data / "tasks.jsonl"
    task_rows = [json.loads(line) for line in task_file.read_text().splitlines() if line.strip()]
    if not set(TASK_IDS).issubset({row["instance_id"] for row in task_rows}):
        raise ValueError("Diagnostic tasks missing")
    snapshot_hashes = {task: sha256(data / "snapshots" / f"{task}.tgz") for task in TASK_IDS}
    image_info = json.loads(subprocess.check_output(["docker", "image", "inspect", args.image], text=True))
    image_env = image_info[0]["Config"]["Env"]
    if "PYTEST_PLUGINS=container_provenance" not in image_env:
        raise ValueError("Image lacks the required snapshot import provenance plugin")
    with urllib.request.urlopen(args.api_base.rstrip("/") + "/models", timeout=10) as response:
        served_models = json.load(response)
    if not {"main_lora", "tool_lora"}.issubset({m["id"] for m in served_models["data"]}):
        raise ValueError("Inference server does not serve both unchanged adapters")

    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    metadata = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "archive_sha256": EXPECTED_HASHES,
        "changed_files": changed,
        "task_ids": TASK_IDS,
        "tasks_sha256": sha256(task_file),
        "snapshot_sha256": snapshot_hashes,
        "image_inspect": image_info,
        "served_models": served_models,
        "budget": budget,
        "versions": {n: importlib.metadata.version(n) for n in ["swegemma", "adk-submission", "adk-eval-core", "vllm"]},
        "design": "Fresh baseline then candidate, sequential tasks on the same server and image; one sample per task, not held-out or statistically conclusive.",
    }
    save(output / "metadata.json", metadata)
    summaries = {}
    for label, archive in archives.items():
        source = output / "sources" / label
        with zipfile.ZipFile(archive) as z:
            z.extractall(source)
        adapters = discover_adapters(source)
        models = setup_gemma_model_registry(api_base=args.api_base, api_key="EMPTY", adapter_manifest=adapters)
        config = EvalConfig(
            tasks_path=task_file,
            snapshots_dir=data / "snapshots",
            wheels_dir=data / "wheels",
            graph_dir=str(data / "graphs"),
            embeddings_dir=str(data / "embeddings"),
            submission_dir=source,
            results_dir=output / label,
            models=models,
            adapter_manifest=adapters,
            image=args.image,
            sandbox="docker",
            task_ids=TASK_IDS,
            concurrency=1,
            display_mode="quiet",
            **budget,
        )
        evaluator = Evaluator(config)
        if label == "baseline":
            control_config = replace(config, results_dir=output / "reference_controls")
            controls = []
            try:
                for task in load_tasks(task_file):
                    if task.instance_id not in {"requests_7315", "fastapi_14258", "rich_3052"}:
                        continue
                    snapshot, base_snapshot, snapshot_patch = resolve_task_snapshot_paths(
                        config.snapshots_dir, task.instance_id, task.repo
                    )
                    control = await verify_task(
                        evaluator.docker, control_config, task, snapshot,
                        base_snapshot_path=base_snapshot,
                        patch_path=snapshot_patch,
                        agent_patch=task.patch,
                        agent_error=None,
                        trace=SessionTrace(),
                        start_time=time.perf_counter(),
                    )
                    controls.append(control)
                    append_task_result(control, control_config.results_dir, controls)
                    print(f"REFERENCE CONTROL {task.instance_id}: {control.resolved}", flush=True)
                    if not control.resolved or "IMPORT_PROVENANCE " not in control.test_output:
                        raise RuntimeError(f"Untrusted grading environment: {task.instance_id}")
                if len(controls) != 3:
                    raise RuntimeError("Missing reference controls")
            finally:
                evaluator.docker.cleanup_all()
        print(f"START {label}", flush=True)
        result = await evaluator.run()
        summaries[label] = [
            {
                "instance_id": task.instance_id,
                "resolved": task.resolved,
                "test_exit_code": task.test_exit_code,
                "error": task.error,
                "patch_bytes": len(task.agent_patch.encode()),
                "tool_calls": task.tool_calls,
                "llm_calls": task.total_llm_calls,
                "duration_seconds": task.duration_seconds,
            }
            for task in result.task_results
        ]
        save(output / "comparison_summary.json", summaries)
        print(f"COMPLETE {label}: {result.resolved}/{result.total}", flush=True)
    metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save(output / "metadata.json", metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/v1")
    asyncio.run(main(parser.parse_args()))
