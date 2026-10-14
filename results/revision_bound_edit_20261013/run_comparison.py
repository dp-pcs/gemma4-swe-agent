#!/usr/bin/env python3
"""Frozen revision-bound editing development screen, with CPU controls before inference.

Modes are mutually exclusive. --cpu-controls-only needs Docker but no serving
endpoint or model objects. --preflight-only compiles both actual submissions
with current LiteLlm objects, tools and skill executor, with socket connections
prohibited; it cannot certify Docker, grading or backend reasoning enforcement.
--evaluation-only requires parent approval in the plan (approved_task_ids,
controls_manifest_sha256, reasoning_proof_sha256) and matching explicit CLI
hashes. CPU artifacts bind immutable selection inputs rather than approval-plan
bytes, so adding approval fields does not invalidate the frozen selection.

All artifacts go below this runner's directory. Historical runner/SDK/ZIPs are
never modified. The official SDK setup and grader are deliberately unchanged.
Thinking/history semantics come only from the current compiler's official
LiteLlm bridge. Preflight and every task inspect actual compiled models and tools.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import re
import signal
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
EXPECTED_HASHES = {
    "baseline": "75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142",
    "candidate": "8f69efd70fbdffa8924f10d60a1117fd0f98cb838bc137b7b172af79bd3f440b",
}
EXPECTED_VERSIONS = {"swegemma": "0.2.11", "adk-submission": "0.2.13", "adk-eval-core": "0.1.0"}
BUDGET = {"timeout_seconds": 90, "max_tool_calls": 40, "max_time_minutes": 4, "max_turns": 100}
SAMPLING = {"temperature": 0.2, "top_p": 0.95, "max_output_tokens": 16384,
            "thinking_config": {"thinking_budget": 4096, "include_thoughts": True}}
CANDIDATE_SAMPLING = SAMPLING
# Backend aliases remain both; source declarations and compiled trees differ.
ALIASES = ["main_lora", "tool_lora"]
ARM_ALIASES = {"baseline": ALIASES, "candidate": ["main_lora"]}
EXPECTED_ARCHIVE_DELTA = {
    "changed": ["agent.yaml", "prompts/system.md"],
    "added": ["skills/revision-edit/SKILL.md", "skills/revision-edit/scripts/repair.py"],
    "removed": ["adapters/tool_lora/adapter_config.json", "adapters/tool_lora/adapter_model.safetensors",
                "prompts/analyzer.md", "sub_agents/code_analyzer.yaml"],
}
CANDIDATE_MEMBERS = sorted([
    "adapters/main_lora/adapter_config.json", "adapters/main_lora/adapter_model.safetensors",
    "agent.yaml", "configs/sampling.yaml", "eval_config.yaml", "prompts/system.md",
    *EXPECTED_ARCHIVE_DELTA["added"],
])
CANDIDATE_TOOLS = ["submit_patch", "list_skills", "load_skill", "load_skill_resource", "run_skill_script"]
FROZEN_TASK_IDS = [
    "fastapi_13920", "rich_4075", "fastapi_14356", "rich_3471", "fastapi_14301", "rich_3894",
    "fastapi_9425", "rich_3518", "fastapi_14485", "rich_3506", "fastapi_13713", "rich_3454",
]
SERVER_VERSION = "0.19.1"
PACKAGES = {"requests": ["requests", "requests.sessions"], "fastapi": ["fastapi", "fastapi.routing"],
            "rich": ["rich", "rich.prompt"], "httpx": ["httpx", "httpx._client"]}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def object_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def safe_id(task_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", task_id) or task_id in {".", ".."}:
        raise ValueError(f"Unsafe task ID: {task_id}")
    return task_id


def artifact(path: Path, root: Path) -> dict:
    return {"path": str(path.relative_to(root)), "sha256": sha256(path), "bytes": path.stat().st_size}


def checked_artifact(root: Path, item: dict) -> Path:
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing/unsafe artifact: {item}")
    if sha256(path) != item["sha256"] or path.stat().st_size != item.get("bytes", path.stat().st_size):
        raise ValueError(f"Artifact hash/size changed: {path}")
    return path


def provenance(output: str, repo: str) -> list[dict]:
    package = repo.rsplit("/", 1)[-1].lower()
    if package not in PACKAGES:
        raise ValueError(f"Unsupported provenance repository {repo}")
    records = []
    for line in output.splitlines():
        if "IMPORT_PROVENANCE " in line:
            records.append(json.loads(line.split("IMPORT_PROVENANCE ", 1)[1].strip()))
    if len(records) < 2 or "IMPORT_PROVENANCE_REJECTED" in output:
        raise ValueError("Missing session-start/collection-finish snapshot import provenance")
    for record in records:
        for module in PACKAGES[package]:
            origin = PurePosixPath(record.get(module, ""))
            roots = [PurePosixPath("/workspace") / package, PurePosixPath("/workspace/src") / package]
            if ".." in origin.parts or not any(origin.is_relative_to(root) for root in roots):
                raise ValueError(f"Non-snapshot import {module}: {origin}")
    return records


@contextmanager
def no_connections():
    """Fail instead of making an unexpected preflight network connection."""
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    def blocked(*args, **kwargs):
        raise RuntimeError("Network connections prohibited during offline preflight")
    socket.socket.connect = socket.socket.connect_ex = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_connect_ex


def load_sdk():
    # Only entered after argparse and exact installed-version checks. No vllm import.
    global SessionTrace, ModelRegistry, discover_adapters, compile_submission, LiteLlm
    global EvalConfig, Evaluator, resolve_task_snapshot_paths, verify_task, TaskResult
    global load_tasks, append_task_result, SwegemmaContext, AdkSandboxCodeExecutor
    global resolve_swegemma_adapter, discover_declared_models, save_trace_artifact
    global _validate_junit_xml, _extract_test_functions_from_patch, _node_matches_requirement
    from adk_eval_core.tracing import SessionTrace
    from adk_submission import ModelRegistry, discover_adapters, compile_submission
    from adk_submission.discovery import discover_declared_models
    from google.adk.models.lite_llm import LiteLlm
    from swegemma import EvalConfig, Evaluator
    from swegemma.context import SwegemmaContext
    from swegemma.deduplication import resolve_task_snapshot_paths
    from swegemma.harness.agent_runner import resolve_swegemma_adapter
    from swegemma.harness.verification import (
        verify_task, save_trace_artifact, _validate_junit_xml,
        _extract_test_functions_from_patch, _node_matches_requirement,
    )
    from swegemma.models import TaskResult, load_tasks
    from swegemma.results import append_task_result
    from swegemma.sandbox import AdkSandboxCodeExecutor


def make_manager(config, directory: Path):
    from swegemma.sandbox.docker import ContainerManager

    class OfflineTimeoutContainerManager(ContainerManager):
        """Historical network=none timeout sink; also preserve raw command/JUnit evidence."""
        def start(self) -> str:
            if self.config.network_mode != "none" or self.config.reuse_containers:
                raise ValueError("Timeout sink requires isolated, non-reused containers")
            container_id = super().start()
            try:
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
            except BaseException:
                self.cleanup_all()
                raise
            return container_id

        def exec(self, container_id: str, command: str, *, timeout: int | None = None):
            result = super().exec(container_id, command, timeout=timeout)
            record = {"utc": utc(), "container_id": container_id, "command": command, "timeout": timeout,
                      "exit_code": result.exit_code, "stdout": result.stdout, "stderr": result.stderr}
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "commands.jsonl").open("a") as stream:
                stream.write(json.dumps(record, default=str) + "\n")
            match = re.search(r"--junitxml=(/tmp/_swegemma_junit_[A-Za-z0-9]+\.xml)\b", command)
            if match:
                # Observation only: do not change pytest flags, result, tests, or grader.
                xml_result = super().exec(container_id, "cat " + match.group(1), timeout=timeout)
                self.last_junit = xml_result.stdout if xml_result.exit_code == 0 else ""
                (directory / "junit.xml").write_text(self.last_junit)
            return result

    manager = OfflineTimeoutContainerManager(config)
    manager.last_junit = ""
    return manager


def make_evaluator(config, directory: Path):
    class PairedEvaluator(Evaluator):
        async def _run_agent_sandbox(self, *args, **kwargs):
            from swegemma.harness import agent_runner
            original_trace = agent_runner.SessionTrace
            original_compile, original_runner = agent_runner.compile_submission, agent_runner.Runner
            arm = Path(config.submission_dir).name
            if arm not in ARM_ALIASES:
                raise ValueError("Evaluation source must be an archive-validated arm")
            def checked_compile(*compile_args, **compile_kwargs):
                agent = original_compile(*compile_args, **compile_kwargs)
                self.last_compiled_contract = {"compiled_models": compiled_model_contract(agent, arm)}
                save(directory / "compiled_contract.json", self.last_compiled_contract)
                return agent

            class ContractRunner(original_runner):
                def __init__(self, *runner_args, **runner_kwargs):
                    super().__init__(*runner_args, **runner_kwargs)
                    self.contract_app = runner_kwargs["app"]
                    self.contract_sessions = runner_kwargs["session_service"]

                async def run_async(self, *run_args, **run_kwargs):
                    session = await self.contract_sessions.get_session(app_name=self.contract_app.name,
                        user_id=run_kwargs["user_id"], session_id=run_kwargs["session_id"])
                    if session is None:
                        raise ValueError("Actual task session missing for compiled-tool verification")
                    owner.last_compiled_contract["bound_tools"] = await compiled_tool_contract(
                        self.contract_app.root_agent, arm, session_service=self.contract_sessions, session=session)
                    save(directory / "compiled_contract.json", owner.last_compiled_contract)
                    async for event in super().run_async(*run_args, **run_kwargs):
                        yield event
            owner = self
            class IncrementalTrace(original_trace):
                def __init__(self, *trace_args, **trace_kwargs):
                    super().__init__(*trace_args, **trace_kwargs)
                    owner.last_agent_trace = self

                def record_event(self, event):
                    super().record_event(event)
                    save(directory / "inflight_trace.json", self.to_dict(format="legacy"))

                def record_custom(self, *event_args, **event_kwargs):
                    super().record_custom(*event_args, **event_kwargs)
                    save(directory / "inflight_trace.json", self.to_dict(format="legacy"))
            # Sequential observation/contract guards only: native execution and
            # grading are unchanged; all patched symbols are always restored.
            agent_runner.SessionTrace = IncrementalTrace
            agent_runner.compile_submission = checked_compile
            agent_runner.Runner = ContractRunner
            try:
                result = await super()._run_agent_sandbox(*args, **kwargs)
                self.last_agent_error = result[1]
                self.last_agent_trace = result[2]
                self.last_agent_patch = result[0]
                return result
            finally:
                agent_runner.SessionTrace = original_trace
                agent_runner.compile_submission, agent_runner.Runner = original_compile, original_runner
    evaluator = PairedEvaluator(config)
    evaluator.sandbox = evaluator.docker = make_manager(evaluator.docker.config, directory)
    evaluator.last_agent_error = evaluator.last_agent_trace = None
    evaluator.last_agent_patch = ""
    evaluator.last_compiled_contract = None
    return evaluator


def registered_models(source: Path, api_base: str, arm: str):
    # Current CLI registry shape, explicit endpoints and real LiteLlm objects.
    # Current .13 compiler owns the thinking-budget/history bridge; no second
    # conversion or thought-filtering convention is installed here.
    models = ModelRegistry()
    adapters = discover_adapters(source)
    aliases = ARM_ALIASES[arm]
    declared = sorted(name.strip() for name in discover_declared_models(source))
    if sorted(adapters.adapters) != sorted(aliases) or declared != ["gemma-4-31b-it-qat-w4a16-ct"]:
        raise ValueError(f"Source {arm} adapter declarations/discovery differ: {declared}, {list(adapters.adapters)}")
    for name in declared:
        target = name if name.startswith(("openai/", "hosted_vllm/", "custom/")) else "openai/" + name
        models.register(name, LiteLlm(model=target, api_base=api_base, api_key="EMPTY", num_retries=5))
    for name in adapters.adapters:
        model = LiteLlm(model="openai/" + name, api_base=api_base, api_key="EMPTY", num_retries=5)
        models.register(name, model)
        models.register("adapter:" + name, model)
    for alias in aliases:
        if models.get(alias).model != "openai/" + alias:
            raise ValueError(f"Incorrect LiteLlm alias mapping: {alias}")
    if set(models.list_available()) != set(declared + aliases + ["adapter:" + name for name in aliases]):
        raise ValueError(f"Unexpected registered models for {arm}")
    return models, adapters


def compiled_model_contract(agent, arm: str) -> list[dict]:
    from google.adk.tools.agent_tool import AgentTool
    seen, records = set(), []
    def visit(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        model = getattr(node, "model", None)
        if model is not None:
            config = node.generate_content_config
            extra = model._additional_args.get("extra_body", {})
            if (not isinstance(model, LiteLlm) or extra.get("thinking_token_budget") != 4096
                    or extra.get("chat_template_kwargs", {}).get("enable_thinking") is not True
                    or model.__dict__.get("_adk_include_thoughts") is not True
                    or config.model_dump(exclude_none=True).get("thinking_config") != SAMPLING["thinking_config"]
                    or config.temperature != 0.2 or config.top_p != 0.95
                    or config.max_output_tokens != (SAMPLING if arm == "baseline" else CANDIDATE_SAMPLING)["max_output_tokens"]):
                raise ValueError(f"Official compiled thinking/sampling bridge differs for {arm}/{node.name}")
            records.append({"agent": node.name, "model": model.model, "extra_body": extra,
                            "include_thoughts": model.__dict__["_adk_include_thoughts"],
                            "generate_content_config": config.model_dump(exclude_none=True)})
        for child in node.sub_agents:
            visit(child)
        for tool in getattr(node, "tools", []):
            if isinstance(tool, AgentTool):
                visit(tool.agent)
    visit(agent)
    if {record["model"] for record in records} != {"openai/" + alias for alias in ARM_ALIASES[arm]}:
        raise ValueError(f"Actual compiled {arm} agent tree differs from its source adapter aliases")
    if arm == "candidate" and (len(records) != 1 or agent.sub_agents
                               or any(isinstance(tool, AgentTool) for tool in agent.tools)):
        raise ValueError("Candidate must compile one main agent with no analyzer/AgentTool")
    return records


async def compiled_tool_contract(agent, arm: str, *, session_service=None, session=None) -> dict:
    """Bind real native tools with a legitimate ADK context; never infer names from YAML."""
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.models.llm_request import LlmRequest
    from google.adk.sessions import InMemorySessionService
    from google.adk.tools.agent_tool import AgentTool
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.base_toolset import BaseToolset
    from google.adk.tools.function_tool import FunctionTool
    from google.adk.tools.skill_toolset import SkillToolset
    from google.adk.tools.tool_context import ToolContext

    if session_service is None:
        session_service = InMemorySessionService()
        session = await session_service.create_session(app_name="revision_preflight", user_id="preflight")
    records, seen = [], set()

    async def visit(node):
        if id(node) in seen:
            return
        seen.add(id(node))
        invocation = InvocationContext(invocation_id="revision_contract_" + session.id,
            agent=node, session=session, session_service=session_service)
        context = ToolContext(invocation)
        instruction = getattr(node, "instruction", "")
        if not isinstance(instruction, str):
            raise ValueError("Compiled instruction must be a concrete string")
        request = LlmRequest()
        request.append_instructions([instruction])
        exposed, toolsets = [], []
        for entry in getattr(node, "tools", []):
            if isinstance(entry, BaseToolset):
                toolsets.append(entry)
                if isinstance(entry, SkillToolset):
                    # This API may resolve tools from actual session state.
                    exposed.extend(await entry.get_tools(context))
                else:
                    exposed.extend(await entry.get_tools_with_prefix(context))
                await entry.process_llm_request(tool_context=context, llm_request=request)
            else:
                exposed.append(entry if isinstance(entry, BaseTool) else FunctionTool(entry))
        for tool in exposed:
            await tool.process_llm_request(tool_context=context, llm_request=request)
        declarations = [declaration.model_dump(exclude_none=True)
            for bound in (request.config.tools or []) for declaration in (bound.function_declarations or [])]
        names = [tool.name for tool in exposed]
        declaration_names = [declaration["name"] for declaration in declarations]
        if arm == "candidate":
            if (len(names) != 5 or set(names) != set(CANDIDATE_TOOLS)
                    or len(declaration_names) != 5 or set(declaration_names) != set(CANDIDATE_TOOLS)
                    or len(toolsets) != 1 or not isinstance(toolsets[0], SkillToolset)
                    or toolsets[0].tool_name_prefix
                    or any(isinstance(tool, AgentTool) for tool in exposed)):
                raise ValueError(f"Candidate native bound function surface differs: {names}, {declaration_names}")
        schema_text = json.dumps(declarations, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        bound_instruction = request.config.system_instruction or ""
        if not isinstance(bound_instruction, str):
            raise ValueError("Bound native instruction must be text")
        records.append({"agent": node.name, "exposed_tool_names": names,
            "function_declarations": declarations, "tool_schema_chars": len(schema_text),
            "tool_schema_sha256": hashlib.sha256(schema_text.encode()).hexdigest(),
            "compiled_instruction_chars": len(instruction), "bound_instruction_chars": len(bound_instruction),
            "bound_instruction_sha256": hashlib.sha256(bound_instruction.encode()).hexdigest(),
            "bound_instruction": bound_instruction,
            "token_count": None, "token_count_note": "No tokenizer or actual provider token count available; character counts only."})
        for child in getattr(node, "sub_agents", []):
            await visit(child)
        for tool in exposed:
            if isinstance(tool, AgentTool):
                await visit(tool.agent)

    await visit(agent)
    return {"agents": records, "scope": "Actual compiled tools bound offline through native process_llm_request; no model call. Compiled instruction plus native toolset instructions, not full runtime history/user prompt."}


def config_for(data: Path, source: Path, directory: Path, image: str, models, adapters, ids: list[str]):
    return EvalConfig(tasks_path=data / "tasks.jsonl", snapshots_dir=data / "snapshots", wheels_dir=data / "wheels",
                      graph_dir=str(data / "graphs"), embeddings_dir=str(data / "embeddings"), submission_dir=source,
                      results_dir=directory, models=models, adapter_manifest=adapters, image=image, sandbox="docker",
                      task_ids=ids, concurrency=1, display_mode="quiet", **BUDGET)


def persist(result, directory: Path, running: list, extra: dict | None = None) -> dict:
    raw_status = result.status
    result.status = ("SUCCESS" if result.resolved else
                     "TIMEOUT" if re.search(r"timeout|timed out", result.error or "", re.IGNORECASE) else
                     "ERROR" if result.error else "FAILED")
    running.append(result)
    append_task_result(result, directory, running)
    for subdir, suffix, text in [("patches", ".patch", result.agent_patch), ("test_outputs", ".log", result.test_output)]:
        target = directory / subdir / (safe_id(result.instance_id) + suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text or "")
    if result.trace is not None and not result.trace_json_path:
        result.trace_json_path = save_trace_artifact(result.trace, directory, result.instance_id)
    record = json_safe(result.model_dump(exclude={"trace"}))
    record.update({"instance_id": result.instance_id, "repo": result.repo, "resolved": result.resolved,
                   "error": result.error, "trace_json_path": result.trace_json_path, "total_llm_calls": result.total_llm_calls,
                   "raw_harness_status": raw_status, "patch_bytes": len((result.agent_patch or "").encode())})
    record.update(extra or {})
    save(directory / "records" / (safe_id(result.instance_id) + ".json"), record)
    return record


def summarize(ids: list[str], held_out: list[str], diagnostics: list[str], results: dict, status: str, trusted: bool) -> dict:
    pairs = []
    for task_id in ids:
        arms = {arm: results[arm].get(task_id) for arm in results}
        outcome = "incomplete"
        if all(arms.values()):
            b, c = arms["baseline"]["resolved"], arms["candidate"]["resolved"]
            outcome = "gain" if c and not b else "regression" if b and not c else "unchanged_success" if b else "unchanged_failure"
        pairs.append({"instance_id": task_id, "split": "held_out" if task_id in held_out else "diagnostic",
                      "cohort_role": "previously_exposed_development", "outcome": outcome, "arms": arms})
    aggregates = {}
    for split, selected_ids in [("held_out", held_out), ("diagnostic", diagnostics)]:
        aggregates[split] = {"cohort_role": "previously_exposed_development",
                             "legacy_field_not_fresh_holdout": True,
                             "expected_tasks_per_arm": len(selected_ids), "paired_outcomes": {
            key: sum(p["outcome"] == key for p in pairs if p["instance_id"] in selected_ids)
            for key in ["gain", "regression", "unchanged_success", "unchanged_failure", "incomplete"]}, "arms": {}}
        for arm in results:
            rows = [results[arm][task_id] for task_id in selected_ids if task_id in results[arm]]
            aggregates[split]["arms"][arm] = {"completed": len(rows), "resolved": sum(row["resolved"] for row in rows),
                "duration_seconds": sum(row["duration_seconds"] for row in rows), "tool_calls": sum(row.get("tool_calls", 0) for row in rows),
                "llm_calls": sum(row["total_llm_calls"] for row in rows), "errors": sum(bool(row["error"]) for row in rows),
                "resolution_rate": sum(row["resolved"] for row in rows) / len(selected_ids) if selected_ids and len(rows) == len(selected_ids) else None}
    return {"status": status, "controls_trusted": trusted, "aggregates": aggregates, "taskwise_pairs": pairs,
            "cohort_role": "previously_exposed_development",
            "legacy_held_out_fields_role": "previously_exposed_development",
            "interpretation": "Previously exposed development cases; held_out keys retain the historical schema and do not mean fresh held-out validation. One sample per frozen task/arm, alternating order. Passing real salvage patches can resolve after agent timeout; empty patches, untrusted imports and missing/skipped required tests cannot. No post-model substitution or promotion/statistical claim."}


def validate_plan(plan: dict) -> tuple[list[str], list[str], list[str]]:
    held_out, diagnostics = plan.get("held_out_task_ids", plan.get("task_ids", [])), plan.get("diagnostic_task_ids", [])
    ids = plan.get("task_ids", held_out + diagnostics)
    if (plan.get("schema_version") != 1 or ids != FROZEN_TASK_IDS or held_out != FROZEN_TASK_IDS or diagnostics != []
            or plan.get("tasks_per_configuration") != len(ids) or held_out + diagnostics != ids
            or plan.get("budgets") != BUDGET or plan.get("archive_sha256") != EXPECTED_HASHES
            or plan.get("expected_versions") != EXPECTED_VERSIONS
            or plan.get("changed_members") != EXPECTED_ARCHIVE_DELTA["changed"]
            or plan.get("archive_delta") != EXPECTED_ARCHIVE_DELTA
            or plan.get("sampling") != SAMPLING or plan.get("candidate_sampling") != SAMPLING
            or plan.get("arm_model_aliases") != ARM_ALIASES
            or plan.get("candidate_exposed_tool_names") != CANDIDATE_TOOLS
            or plan.get("cohort_role") != "previously_exposed_development"
            or plan.get("legacy_held_out_fields_role") != "previously_exposed_development"
            or plan.get("model_aliases") != ALIASES
            or plan.get("server") not in [{"version": SERVER_VERSION, "max_model_len": length}
                                         for length in (32768, 65536)]):
        raise ValueError("Unexpected frozen selection, archive identity, current versions, changed members, aliases or budgets")
    for task_id in ids:
        safe_id(task_id)
    return ids, held_out, diagnostics


def validate_wheels(plan: dict, args) -> list[dict]:
    names = {name.replace("-", "_") + "-" + version + "-py3-none-any.whl" for name, version in EXPECTED_VERSIONS.items()}
    rows = []
    for entry in plan["runtime_wheels"]:
        declared = Path(entry["path"])
        path = args.runtime_wheels / declared.name if args.runtime_wheels else declared if declared.is_absolute() else args.plan.parent / declared
        path = path.resolve()
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Runtime wheel identity changed: {path}")
        distribution_name = next((name for name, version in EXPECTED_VERSIONS.items()
                                  if path.name == name.replace("-", "_") + "-" + version + "-py3-none-any.whl"), None)
        if distribution_name is None:
            raise ValueError(f"Unexpected runtime wheel name: {path.name}")
        installed = importlib.metadata.distribution(distribution_name)
        with zipfile.ZipFile(path) as wheel:
            for member in wheel.namelist():
                if member.endswith(".py"):
                    installed_source = Path(installed.locate_file(member))
                    if not installed_source.is_file() or hashlib.sha256(wheel.read(member)).hexdigest() != sha256(installed_source):
                        raise ValueError(f"Installed runtime source differs from organizer wheel: {member}")
        rows.append({"name": path.name, "sha256": entry["sha256"], "path": str(path)})
    if len(rows) != 3 or {row["name"] for row in rows} != names:
        raise ValueError("Expected exactly the three current organizer runtime wheels")
    return rows


def validate_archives(args, output: Path) -> dict:
    import yaml
    members, all_members, configs, sources = {}, {}, {}, {}
    archive_hashes = {}
    for arm, archive in {"baseline": args.baseline.resolve(), "candidate": args.candidate.resolve()}.items():
        archive_hashes[arm] = sha256(archive)
        if archive_hashes[arm] != EXPECTED_HASHES[arm]:
            raise ValueError(f"Unexpected {arm} archive hash (legacy candidate prohibited)")
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate ZIP members")
            for name in names:
                path = PurePosixPath(name)
                if (not name or "\\" in name or path.as_posix() != name
                        or path.is_absolute() or ".." in path.parts or name.endswith("/")
                        or (z.getinfo(name).external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError(f"Unsafe/noncanonical ZIP member {name}")
            all_members[arm] = sorted(names)
            members[arm] = {name: z.read(name) for name in names if not name.endswith("/")}
            source = output / "sources" / arm
            z.extractall(source)
            sources[arm] = source
        configs[arm] = yaml.safe_load(members[arm]["eval_config.yaml"])
        if configs[arm]["evaluation"] != BUDGET:
            raise ValueError("Submission budget differs from frozen budget")
    if all_members["candidate"] != CANDIDATE_MEMBERS:
        raise ValueError("Candidate ZIP must contain exactly the frozen eight members")
    baseline, candidate = members["baseline"], members["candidate"]
    delta = {
        "changed": sorted(name for name in baseline.keys() & candidate.keys() if baseline[name] != candidate[name]),
        "added": sorted(candidate.keys() - baseline.keys()),
        "removed": sorted(baseline.keys() - candidate.keys()),
    }
    if delta != EXPECTED_ARCHIVE_DELTA:
        raise ValueError(f"Candidate changed unexpected ZIP bytes/member names: {delta}")
    sampling = {arm: yaml.safe_load(files["configs/sampling.yaml"]) for arm, files in members.items()}
    if sampling != {"baseline": SAMPLING, "candidate": CANDIDATE_SAMPLING}:
        raise ValueError("Both arms must retain identical16384 output and4096 thinking/history sampling")
    return {"sources": sources, "archive_sha256": archive_hashes, "archive_members": all_members,
            "member_sha256": {arm: {name: hashlib.sha256(body).hexdigest() for name, body in files.items()} for arm, files in members.items()},
            "member_bytes": {arm: {name: len(body) for name, body in files.items()} for arm, files in members.items()},
            "changed_members": delta["changed"], "archive_delta": delta, "submission_configs": configs, "sampling": sampling}


def inspect_images(plan: dict, ids: list[str], fallback: str | None) -> tuple[dict, dict]:
    mapping = plan.get("image_map", {})
    if mapping and set(mapping) != set(ids):
        raise ValueError("image_map must cover exactly frozen task IDs")
    inspections, image_ids = {}, {}
    cache = {}
    for task_id in ids:
        requested = mapping.get(task_id, fallback)
        if not requested:
            raise ValueError(f"No frozen image for {task_id}")
        if requested not in cache:
            cache[requested] = json.loads(subprocess.check_output(["docker", "image", "inspect", requested], text=True))
        image = cache[requested]
        if len(image) != 1 or "PYTEST_PLUGINS=container_provenance" not in (image[0]["Config"].get("Env") or []):
            raise ValueError("Image lacks frozen container_provenance plugin")
        image_id = image[0]["Id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise ValueError("Docker did not provide immutable image ID")
        if plan.get("image_ids") is not None and plan["image_ids"].get(task_id) != image_id:
            raise ValueError(f"Image differs from plan-pinned ID for {task_id}")
        inspections[task_id], image_ids[task_id] = image, image_id
    return inspections, image_ids


def junit_check(xml: str, task, kind: str, *, reference_clean: bool = False) -> tuple[bool, str | None]:
    if kind != "unpatched":
        return _validate_junit_xml(xml, fail_to_pass=task.FAIL_TO_PASS, pass_to_pass=task.PASS_TO_PASS, test_patch=task.test_patch)
    if not reference_clean:
        return False, "Negative control requires a clean reference in the same environment"
    try:
        root = ET.fromstring(xml)
        cases = list(root.findall(".//testcase"))
        if not cases:
            return False, "Unpatched control has no tests"
        # A source bug may fail in a fixture before the test body runs. Only
        # failures/errors in gold tests qualify, and only after a clean reference.
        # Missing/skipped tests and errors outside changed gold tests stay rejected.
        changed_tests = set()
        changed_modules = set()
        module = None
        for line in task.test_patch.splitlines():
            if line.startswith("+++ "):
                path = line[4:].removeprefix("b/")
                module = path[:-3].replace("/", ".") if path.endswith(".py") else None
                if module:
                    # Pytest may choose tests/ as rootdir, removing that prefix.
                    changed_modules.update((module, module.removeprefix("tests.")))
            added = re.match(r"^\+\s*(?:async\s+)?def\s+(test_\w+)\s*\(", line)
            context = re.match(r"^@@.*@@.*\bdef\s+(test_\w+)\s*\(", line)
            if module and (match := added or context):
                changed_tests.update((mod, match.group(1)) for mod in (module, module.removeprefix("tests.")))
        allowed_errors = set()
        for tc in cases:
            error = tc.find("error")
            if error is None:
                continue
            cls, name = tc.attrib.get("classname", ""), tc.attrib.get("name", "")
            changed = any((cls == mod or cls.startswith(mod + ".")) and name.split("[", 1)[0] == fn
                          for mod, fn in changed_tests)
            candidates = [name, cls + "::" + name, cls + "." + name, cls.replace(".", "/") + ".py::" + name]
            explicit_failure = any(
                _node_matches_requirement(node, req, req.split("::")[-1], req.split("::")[-1].split("[")[0])
                for req in task.FAIL_TO_PASS for node in candidates)
            if not (changed or explicit_failure) or tc.find("skipped") is not None:
                return False, "Unpatched control has unexpected test errors"
            allowed_errors.add(id(tc))
        required = list(task.FAIL_TO_PASS) + list(task.PASS_TO_PASS)
        if not required:
            required = _extract_test_functions_from_patch(task.test_patch)
        if not required:
            return False, "No identifiable required gold tests"
        required_failures = 0
        for req in required:
            short, base = req.split("::")[-1], req.split("::")[-1].split("[")[0]
            matching = []
            for tc in cases:
                name, cls = tc.attrib.get("name", ""), tc.attrib.get("classname", "")
                candidates = [name, cls + "::" + name, cls + "." + name, cls.replace(".", "/") + ".py::" + name]
                if any(_node_matches_requirement(node, req, short, base) for node in candidates):
                    matching.append(tc)
            if not matching or any(tc.find("skipped") is not None or (tc.find("error") is not None and id(tc) not in allowed_errors) for tc in matching):
                return False, f"Required gold test missing/skipped/errored: {req}"
            if any(tc.find("failure") is not None or tc.find("error") is not None for tc in matching):
                if req in task.PASS_TO_PASS:
                    return False, f"PASS_TO_PASS test failed unpatched: {req}"
                required_failures += 1
        if not required_failures and not task.FAIL_TO_PASS:
            # A parameter-table edit may be outside a test body; the SDK's hunk
            # header names the preceding function, not its parametrized consumer.
            # A clean reference and assertion failure in the changed gold module
            # still establish the negative oracle. Explicit requirements stay strict.
            required_failures = sum(
                tc.find("failure") is not None
                and any(tc.attrib.get("classname", "") == mod
                        or tc.attrib.get("classname", "").startswith(mod + ".")
                        for mod in changed_modules)
                for tc in cases
            )
        if not required_failures:
            return False, "No required gold failure/error in unpatched control"
        return True, None
    except (ET.ParseError, ValueError) as exc:
        return False, f"Invalid unpatched JUnit: {exc}"


def selection_contract(plan: dict, ids: list[str], tasks: dict, snapshots: dict, image_ids: dict, wheels: list[dict], archives: dict) -> dict:
    return {"task_ids": ids, "selection_seed": plan.get("selection_seed"), "task_file_sha256": plan["task_file_sha256"],
            "snapshots": snapshots, "image_ids": image_ids, "archive_sha256": archives["archive_sha256"],
            "archive_members": archives["archive_members"], "member_sha256": archives["member_sha256"],
            "member_bytes": archives["member_bytes"],
            "expected_versions": EXPECTED_VERSIONS, "budgets": BUDGET, "sampling": SAMPLING,
            "candidate_sampling": SAMPLING, "changed_members": archives["changed_members"],
            "archive_delta": archives["archive_delta"], "model_aliases": ALIASES,
            "arm_model_aliases": ARM_ALIASES, "candidate_exposed_tool_names": CANDIDATE_TOOLS,
            "cohort_role": "previously_exposed_development", "server": plan["server"],
            "runtime_wheels": sorted([{k: row[k] for k in ["name", "sha256"]} for row in wheels], key=lambda row: row["name"]),
            "task_content_sha256": {task_id: object_hash(dataclasses.asdict(tasks[task_id])) for task_id in ids}}


def verify_controls(args, plan: dict, contract: dict, tasks: dict) -> list[dict]:
    if not args.controls_manifest or not args.controls_manifest_sha256:
        raise ValueError("Evaluation requires explicitly approved CPU control manifest and hash")
    path = args.controls_manifest.resolve()
    if sha256(path) != args.controls_manifest_sha256 or plan.get("controls_manifest_sha256") != args.controls_manifest_sha256:
        raise ValueError("CPU manifest hash differs from parent-approved hash")
    if plan.get("approved_task_ids") != contract["task_ids"]:
        raise ValueError("Evaluation plan has not approved the exact ordered CPU selection")
    manifest = json.loads(path.read_text())
    # CPU controls never invoke inference. Preserve their original server metadata
    # while independently requiring proof of the live model-run server below.
    control_contract = {**contract, "server": plan.get("cpu_control_server", plan["server"])}
    if (manifest.get("schema_version") != 1 or manifest.get("status") != "trusted"
            or manifest.get("selection_contract") != control_contract
            or manifest.get("selection_contract_sha256") != object_hash(control_contract)):
        raise ValueError("CPU selection/task/snapshot/image/runtime identity differs or controls untrusted")
    checked = {item["path"]: checked_artifact(path.parent, item) for item in manifest["artifacts"]}
    expected = {(task_id, kind) for task_id in contract["task_ids"] for kind in ["unpatched", "reference"]}
    records = manifest["controls"]
    if len(records) != 2 * len(tasks) or {(row["instance_id"], row["kind"]) for row in records} != expected:
        raise ValueError("Missing/duplicate CPU controls")
    clean_references = set()
    for row in sorted(records, key=lambda item: item["kind"] != "reference"):
        task_id, kind = row["instance_id"], row["kind"]
        record_name = f"controls/{kind}/records/{task_id}.json"
        output_name = f"controls/{kind}/test_outputs/{task_id}.log"
        patch_name = f"controls/{kind}/patches/{task_id}.patch"
        junit_name = f"controls/{kind}/evidence/{task_id}/junit.xml"
        if not {record_name, output_name, patch_name, junit_name}.issubset(checked):
            raise ValueError(f"Missing hashed CPU record/patch/output/JUnit: {task_id}/{kind}")
        if json.loads(checked[record_name].read_text()) != row or not row["trusted"] or row["trust_error"]:
            raise ValueError("CPU manifest record differs or untrusted")
        text = checked[output_name].read_text()
        if provenance(text, tasks[task_id].repo) != row["import_provenance"]:
            raise ValueError("Control import provenance differs")
        if checked[patch_name].read_text() != (tasks[task_id].patch if kind == "reference" else ""):
            raise ValueError("Control patch differs from frozen gold/unpatched input")
        okay, reason = junit_check(checked[junit_name].read_text(), tasks[task_id], kind,
                                  reference_clean=task_id in clean_references)
        if not okay:
            raise ValueError(reason)
        if row["resolved"] != (kind == "reference") or row["test_exit_code"] != (0 if kind == "reference" else 1) or row["error"]:
            raise ValueError("CPU test result does not match expected control outcome")
        if kind == "reference":
            clean_references.add(task_id)
    return records




def validate_server(args, plan: dict, output: Path) -> dict:
    api_base = args.api_base.rstrip("/")
    root = api_base.removesuffix("/v1")
    observed = {}
    for name, url in [("models", api_base + "/models"), ("version", root + "/version"),
                      ("server_info", root + "/server_info"),
                      ("server_info_structured", root + "/server_info?config_format=json")]:
        with urllib.request.urlopen(url, timeout=10) as response:
            observed[name] = json.load(response)
        save(output / "server" / (name + ".json"), observed[name])
    if not set(ALIASES).issubset({row["id"] for row in observed["models"]["data"]}):
        raise ValueError("Server does not expose both frozen adapter aliases")
    if observed["version"].get("version") != SERVER_VERSION:
        raise ValueError("Remote vLLM version differs from 0.19.1")
    length = observed["server_info_structured"]["vllm_config"]["model_config"]["max_model_len"]
    if type(length) is not int or length != plan["server"]["max_model_len"]:
        raise ValueError(f"Live server max_model_len not verifiably {plan['server']['max_model_len']}")
    if not args.reasoning_proof or not args.reasoning_proof_sha256:
        raise ValueError("Missing parent-approved actual backend reasoning enforcement proof")
    proof_path = args.reasoning_proof.resolve()
    if sha256(proof_path) != args.reasoning_proof_sha256 or plan.get("reasoning_proof_sha256") != args.reasoning_proof_sha256:
        raise ValueError("Reasoning proof differs from parent-approved hash")
    proof = json.loads(proof_path.read_text())
    expected = {"api_base": api_base, "version": SERVER_VERSION, "max_model_len": plan["server"]["max_model_len"],
                "thinking_budget": 4096, "enable_thinking": True, "backend_enforcement_verified": True}
    if any(proof.get(key) != value for key, value in expected.items()):
        raise ValueError("Reasoning proof not bound to the live current server and enabled enforced 4096 budget")
    if proof.get("server_info_object_sha256") != object_hash(observed["server_info"]):
        raise ValueError("Backend proof does not bind the live effective /server_info configuration")
    evidence = proof.get("evidence", [])
    kinds = {row.get("kind") for row in evidence}
    if "model_response" not in kinds or not ({"backend_effective_config", "backend_source_enforcement"} & kinds):
        raise ValueError("Proof needs backend enforcement plus actual responses; outbound body alone is insufficient")
    checked = {row["path"]: checked_artifact(proof_path.parent, row) for row in evidence}
    response_paths = {row["path"] for row in evidence if row.get("kind") == "model_response"}
    responses = proof.get("responses", [])
    for alias in ALIASES:
        entries = [row for row in responses if row.get("model") == alias]
        if len(entries) != 1 or entries[0].get("raw_response_path") not in response_paths:
            raise ValueError(f"Missing unambiguous actual raw reasoning response: {alias}")
        row = entries[0]
        response = json.loads(checked[row["raw_response_path"]].read_text())
        message = response["choices"][0]["message"]
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        token_count = ((response.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        if not (isinstance(reasoning, str) and reasoning.strip()) and not (type(token_count) is int and token_count > 0):
            raise ValueError(f"Raw response has no visible reasoning or positive actual reasoning token metadata: {alias}")
        if reasoning and row.get("reasoning_sha256") != hashlib.sha256(reasoning.encode()).hexdigest():
            raise ValueError(f"Captured analysis hash differs: {alias}")
        if response.get("model") != alias or row.get("source") != "live_model":
            raise ValueError(f"Response not explicitly live and bound to served alias: {alias}")
        if "backend_effective_config" not in kinds:
            request_path = row.get("raw_request_path")
            request_paths = {item["path"] for item in evidence if item.get("kind") == "model_request"}
            if request_path not in request_paths:
                raise ValueError("Source enforcement proof also requires actual raw wire requests")
            request = json.loads(checked[request_path].read_text())
            if request.get("model") != alias or request.get("thinking_token_budget") != 4096:
                raise ValueError("Actual wire request lacks backend-enforced thinking_token_budget=4096")
    for index, entry in enumerate(evidence):
        source = checked[entry["path"]]
        target = output / "server" / "proof_evidence" / f"{index:03d}-{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    save(output / "server" / "reasoning_proof.json", proof)
    return {**observed, "reasoning_proof_sha256": args.reasoning_proof_sha256, "reasoning_proof_path": str(proof_path)}


async def main(args) -> None:
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        raise ValueError("--output must be a subdirectory of the new run directory")
    output.mkdir(parents=True, exist_ok=True)
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
                "mode": "preflight" if args.preflight_only else "cpu-controls" if args.cpu_controls_only else "evaluation",
                "design": "Previously exposed frozen 12-task development cohort; dynamic 2*N trusted CPU controls before model setup; per-task image-ID pinning, concurrency one, alternating arms."}
    evaluators, results = {}, {"baseline": {}, "candidate": {}}
    controls, ids, held_out, diagnostics = [], [], [], []
    contract = None
    trusted, status = False, "interrupted"
    save(output / "metadata.json", metadata)
    try:
        plan = json.loads(args.plan.read_text())
        save(output / "evaluation_plan.json", plan)
        ids, held_out, diagnostics = validate_plan(plan)
        versions = {name: importlib.metadata.version(name) for name in EXPECTED_VERSIONS}
        if versions != EXPECTED_VERSIONS:
            raise ValueError(f"Wrong installed SDK versions: {versions}")
        wheels = validate_wheels(plan, args)
        metadata.update({"evaluation_plan_sha256": sha256(args.plan), "versions": versions, "runtime_wheels": wheels,
                         "task_ids": ids, "budget": BUDGET})
        if args.preflight_only:
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
            with no_connections():
                load_sdk()
        else:
            load_sdk()
        archive_info = validate_archives(args, output)
        sources = archive_info.pop("sources")
        metadata.update(archive_info)
        if plan["archive_delta"] != archive_info["archive_delta"] or plan["archive_sha256"] != archive_info["archive_sha256"]:
            raise ValueError("Plan archive delta/identity differs from actual pinned ZIP bytes")
        data = args.data_root.resolve()
        if args.preflight_only:
            compiled = {}
            with no_connections():
                for arm, source in sources.items():
                    models, adapters = registered_models(source, args.api_base, arm)
                    config = config_for(data, source, output / arm, "offline-preflight-no-image", models, adapters, ids)
                    context = SwegemmaContext(graph_dir=config.graph_dir, embeddings_dir=config.embeddings_dir,
                                              budget=config.budget, harness=config.harness)
                    tools = context.create_tools()
                    executor = AdkSandboxCodeExecutor(sandbox=context.sandbox, timeout_seconds=90,
                        start_time=context.task_start_time, max_time_minutes=4, budget_check_fn=context.check_budget)
                    agent = compile_submission(submission_dir=source, tool_registry=tools, model_registry=models,
                        code_executor=executor, script_timeout=90, limits=config.limits,
                        generation_constraints=config.generation_constraints, adapter_manifest=adapters,
                        adapter_resolver_fn=lambda base, info: resolve_swegemma_adapter(base, info, models))
                    compiled[arm] = {"name": agent.name, "type": type(agent).__name__, "models": models.list_available(),
                                     "declared_adapter_aliases": list(adapters.adapters),
                                     "skill_executor": type(executor).__name__, "registry_tool_count_not_exposed": len(tools),
                                     "compiled_models": compiled_model_contract(agent, arm),
                                     "bound_tools": await compiled_tool_contract(agent, arm)}
            save(output / "preflight.json", {"compiled": compiled, "network_connections_prohibited": True,
                "limitations": ["No containers started or grading controls exercised", "No model calls or inference requests", "No live server/version/context/reasoning verification", "Successful compile is not runtime/grading certification"]})
            status = "preflight_complete"
            return
        task_file = data / "tasks.jsonl"
        if sha256(task_file) != plan["task_file_sha256"]:
            raise ValueError("Task corpus differs from frozen plan")
        tasks = {task.instance_id: task for task in load_tasks(task_file) if task.instance_id in ids}
        if set(tasks) != set(ids):
            raise ValueError("Frozen tasks missing")
        images, image_ids = inspect_images(plan, ids, args.image)
        metadata.update({"image_inspect": images, "image_ids": image_ids, "offline_network": {
            "network_mode": "none", "timeout_sink": "10.255.255.1/32",
            "mechanism": "Original host-injected dummy NIC in private namespaces; no default route, veth or agent NET_ADMIN",
            "scope": "Existing TCP timeout fixture compatibility only; not scorer-network parity"}})
        # Empty registry in CPU stage: no LiteLlm construction, endpoint discovery or compilation.
        empty_models = ModelRegistry()
        hydration = Evaluator(config_for(data, sources["baseline"], output / "hydration", image_ids[ids[0]], empty_models, None, ids))
        evaluators["hydration"] = hydration
        tasks = {task_id: hydration._hydrate_task_from_secret(tasks[task_id]) for task_id in ids}
        snapshots, snapshot_metadata = {}, {}
        for task_id in ids:
            task = tasks[task_id]
            if not task.patch.strip() or not (task.test_patch.strip() or task.FAIL_TO_PASS or task.PASS_TO_PASS):
                raise ValueError(f"Missing actual gold patch/test specification for {task_id}")
            paths = resolve_task_snapshot_paths(data / "snapshots", task_id, task.repo)
            if not paths[0]:
                raise ValueError(f"Missing snapshot for {task_id}")
            snapshots[task_id] = paths
            snapshot_metadata[task_id] = [{"sha256": sha256(path), "bytes": path.stat().st_size} if path else None for path in paths]
        contract = selection_contract(plan, ids, tasks, snapshot_metadata, image_ids, wheels, archive_info)
        metadata.update({"selection_contract": contract, "selection_contract_sha256": object_hash(contract),
            "installed_distributions": sorted([{"name": dist.metadata["Name"], "version": dist.version}
                for dist in importlib.metadata.distributions()], key=lambda row: (row["name"] or "").lower()),
            "data_identity_scope": "Task corpus, hydrated task/gold/test content, selected snapshot bytes, runtime wheels and images are bound. Both arms share data-root wheel/graph/embedding paths; those auxiliary trees are not recursively hashed."})
        save(output / "metadata.json", metadata)
        if args.cpu_controls_only:
            metadata["status"] = "controls"
            save(output / "metadata.json", metadata)
            running = {"unpatched": [], "reference": []}
            for task_id in ids:
                task = tasks[task_id]
                snapshot, base, snapshot_patch = snapshots[task_id]
                reference_clean = False
                for kind, patch in [("reference", task.patch), ("unpatched", "")]:
                    directory = output / "controls" / kind
                    evidence = directory / "evidence" / task_id
                    config = config_for(data, sources["baseline"], directory, image_ids[task_id], empty_models, None, ids)
                    evaluator = make_evaluator(config, evidence)
                    evaluators["control"] = evaluator
                    control_start = time.perf_counter()
                    result, origins, valid, reason = None, [], False, None
                    interrupt = None
                    control_trace = SessionTrace()
                    try:
                        result = await verify_task(evaluator.docker, config, task, snapshot, base_snapshot_path=base,
                            patch_path=snapshot_patch, agent_patch=patch, agent_error=None, trace=control_trace, start_time=control_start)
                        origins = provenance(result.test_output, task.repo)
                        valid = ((not result.resolved and result.test_exit_code == 1 and not result.error) if kind == "unpatched"
                                 else (result.resolved and result.test_exit_code == 0 and not result.error))
                        junit_valid, junit_reason = junit_check(evaluator.docker.last_junit, task, kind,
                                                               reference_clean=reference_clean)
                        valid = valid and junit_valid
                        if kind == "reference":
                            reference_clean = valid
                        reason = None if valid else junit_reason or "Control did not produce expected actual test outcome"
                    except BaseException as exc:
                        reason = traceback.format_exc()
                        valid = False
                        if not isinstance(exc, Exception):
                            interrupt = exc
                        if result is None:
                            result = TaskResult(instance_id=task_id, repo=task.repo, resolved=False, agent_patch=patch,
                                test_output="", test_exit_code=-1, duration_seconds=time.perf_counter() - control_start,
                                error=reason, trace=control_trace)
                    finally:
                        evidence.mkdir(parents=True, exist_ok=True)
                        if not (evidence / "junit.xml").exists():
                            (evidence / "junit.xml").write_text(evaluator.docker.last_junit)
                        try:
                            evaluator.docker.cleanup_all()
                        except Exception:
                            valid = False
                            reason = "\n".join(filter(None, [reason, traceback.format_exc()]))
                    row = persist(result, directory, running[kind], {"kind": kind, "trusted": bool(valid),
                        "trust_error": reason, "import_provenance": origins, "image_id": image_ids[task_id]})
                    controls.append(row)
                    save(output / "controls_summary.json", controls)
                    print(f"CONTROL {kind} {task_id}: trusted={valid} resolved={result.resolved}", flush=True)
                    if interrupt is not None:
                        raise interrupt
                    if not valid:
                        status = "controls_failed"
                        raise RuntimeError("CPU control failed: no replacements and model/GPU evaluation prohibited")
            trusted = len(controls) == 2 * len(ids) and all(row["trusted"] for row in controls)
            status = "controls_complete" if trusted else "controls_failed"
            return
        controls = verify_controls(args, plan, contract, tasks)
        trusted = True
        metadata.update({"controls_manifest": str(args.controls_manifest.resolve()), "controls_manifest_sha256": args.controls_manifest_sha256,
                         "controls_trusted": True, "server_runtime": validate_server(args, plan, output), "status": "evaluating"})
        metadata["evaluation_order"] = [{"task_id": task_id, "arms": ["baseline", "candidate"] if index % 2 == 0 else ["candidate", "baseline"]}
                                        for index, task_id in enumerate(ids)]
        save(output / "metadata.json", metadata)
        model_configs = {arm: registered_models(source, args.api_base, arm) for arm, source in sources.items()}
        metadata["registered_models_by_arm"] = {arm: {
            "models": models.list_available(), "declared_adapter_aliases": list(adapters.adapters)}
            for arm, (models, adapters) in model_configs.items()}
        metadata["backend_required_model_aliases"] = ALIASES
        save(output / "metadata.json", metadata)
        running = {"baseline": [], "candidate": []}
        for index, entry in enumerate(metadata["evaluation_order"], 1):
            task_id = entry["task_id"]
            for arm in entry["arms"]:
                models, adapters = model_configs[arm]
                directory = output / arm
                config = config_for(data, sources[arm], directory, image_ids[task_id], models, adapters, ids)
                metadata.setdefault("runtime_configs", {}).setdefault(arm, {})[task_id] = {
                    field.name: json_safe(getattr(config, field.name)) for field in dataclasses.fields(config)}
                save(output / "metadata.json", metadata)
                evaluator = make_evaluator(config, directory / "evidence" / task_id)
                evaluators[arm] = evaluator
                task_start = time.perf_counter()
                log = logging.FileHandler(output / f"{arm}-{task_id}.log")
                log.setFormatter(handler.formatter)
                logging.getLogger().addHandler(log)
                try:
                    print(f"START {arm} {task_id}", flush=True)
                    result = await evaluator.evaluate_task(tasks[task_id], task_index=index, total_tasks=len(ids))
                    raw_resolved, origins, errors = result.resolved, [], []
                    if not evaluator.last_compiled_contract or "bound_tools" not in evaluator.last_compiled_contract:
                        errors.append("Actual per-task compilation/model/tool contract was not verified")
                    if not result.agent_patch.strip():
                        errors.append("No emitted agent patch; cannot resolve")
                    try:
                        origins = provenance(result.test_output, tasks[task_id].repo)
                    except Exception as exc:
                        errors.append(str(exc))
                    if result.resolved:
                        okay, reason = junit_check(evaluator.docker.last_junit, tasks[task_id], "reference")
                        if not okay:
                            errors.append(reason)
                    if errors:
                        result.resolved = False
                        result.error = "\n".join(filter(None, [result.error, *errors]))
                    row = persist(result, directory, running[arm], {"raw_harness_resolved": raw_resolved,
                        "agent_error": evaluator.last_agent_error, "agent_completed_without_error": not bool(evaluator.last_agent_error),
                        "import_provenance": origins, "image_id": image_ids[task_id],
                        "compiled_contract": evaluator.last_compiled_contract})
                except BaseException as exc:
                    error = traceback.format_exc()
                    result = TaskResult(instance_id=task_id, repo=tasks[task_id].repo, resolved=False,
                        agent_patch=evaluator.last_agent_patch, test_output="", test_exit_code=-1,
                        duration_seconds=time.perf_counter() - task_start, error=error, trace=evaluator.last_agent_trace)
                    row = persist(result, directory, running[arm], {"exception": error, "image_id": image_ids[task_id],
                        "compiled_contract": evaluator.last_compiled_contract})
                    if not isinstance(exc, Exception):
                        results[arm][task_id] = row
                        raise
                finally:
                    logging.getLogger().removeHandler(log)
                    log.close()
                    try:
                        evaluator.docker.cleanup_all()
                    except Exception:
                        metadata.setdefault("task_cleanup_errors", []).append({"arm": arm, "task_id": task_id, "error": traceback.format_exc()})
                results[arm][task_id] = row
                save(output / "comparison_summary.json", summarize(ids, held_out, diagnostics, results, "running", trusted))
                print(f"COMPLETE {arm} {task_id}: resolved={row['resolved']} error={row['error']}", flush=True)
        status = "complete"
    except BaseException as exc:
        if isinstance(exc, Exception) and status != "controls_failed":
            status = "failed"
        metadata["error"] = traceback.format_exc()
        logging.exception("Comparison failed/interrupted")
        raise
    finally:
        cleanup_errors = []
        for name, evaluator in evaluators.items():
            try:
                evaluator.docker.cleanup_all()
            except Exception:
                cleanup_errors.append({"name": name, "error": traceback.format_exc()})
        if args.cpu_controls_only and contract is not None:
            save(output / "controls_manifest.json", {"schema_version": 1, "status": "trusted" if trusted else "untrusted",
                "plan_sha256": metadata["evaluation_plan_sha256"], "selection_contract": contract,
                "selection_contract_sha256": object_hash(contract), "controls": controls,
                "artifacts": [artifact(path, output) for path in sorted((output / "controls").rglob("*")) if path.is_file()],
                "expected_control_count": 2 * len(ids), "completed_control_count": len(controls), "finished_utc": utc()})
        metadata.update({"status": status, "finished_utc": utc(), "duration_seconds": time.perf_counter() - start,
                         "controls_trusted": trusted, "cleanup_errors": cleanup_errors})
        save(output / "comparison_summary.json", summarize(ids, held_out, diagnostics, results, status, trusted))
        metadata["artifact_manifest"] = [artifact(path, output) for path in sorted(output.rglob("*"))
                                         if path.is_file() and path.name not in {"metadata.json", "runner.log"}]
        save(output / "metadata.json", metadata)
        logging.getLogger().removeHandler(handler)
        handler.close()


def cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cpu-controls-only", action="store_true", help="Real frozen controls only; no endpoint/model setup")
    mode.add_argument("--evaluation-only", action="store_true", help="Reuse hash-approved trusted controls; never reselect tasks")
    mode.add_argument("--preflight-only", action="store_true", help="Offline real SDK compile; no Docker/model/network requests")
    parser.add_argument("--plan", type=Path, default=ROOT / "evaluation_plan.json")
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New subdirectory under this run directory")
    parser.add_argument("--image", help="Fallback only when plan has no image_map")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--runtime-wheels", type=Path, help="Relocate plan-pinned runtime wheel files")
    parser.add_argument("--controls-manifest", type=Path)
    parser.add_argument("--controls-manifest-sha256")
    parser.add_argument("--reasoning-proof", type=Path)
    parser.add_argument("--reasoning-proof-sha256")
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"Interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
