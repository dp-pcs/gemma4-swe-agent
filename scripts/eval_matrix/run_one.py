"""Run one (arm, task) evaluation with the organizer Evaluator, scorer-style config.

Mirrors the official starter notebook's Phase 1/2 setup (2026-10-12 version):
eval_config.yaml budgets, competition SubmissionLimits, EventsCompactionConfig
(15/2/14336/5) and ContextCacheConfig (2048/1800/10). Only differences from the
scorer: Docker sandbox instead of subprocess, and an optional time scale applied
to max_time_minutes to compensate for local per-call latency.

Usage:
  python run_one.py --arm-dir DIR --task-id ID --data-root DIR --image TAG \
      --endpoint http://127.0.0.1:8000/v1 --out DIR [--time-scale 1.0]
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import litellm
import yaml
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig

litellm.drop_params = True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-dir", required=True, type=Path)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--image", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--time-scale", type=float, default=1.0)
    ap.add_argument("--control", choices=["gold", "empty"],
                    help="Skip the agent and grade the reference patch or an empty patch")
    args = ap.parse_args()

    # The CLI registry reads the endpoint from the environment at build time.
    os.environ["LOCAL_INFERENCE_URL"] = args.endpoint
    from adk_submission import discover_adapters
    from swegemma.cli import _build_cli_model_registry
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits
    from swegemma.evaluate import Evaluator

    arm = args.arm_dir.resolve()
    raw = yaml.safe_load((arm / "eval_config.yaml").read_text()) or {}
    ev = raw.get("evaluation", raw)
    turns = ev.get("max_turns", ev.get("max_llm_calls"))
    max_time = float(ev.get("max_time_minutes", 60.0)) * args.time_scale

    limits, gen_constraints = build_submission_limits()
    args.out.mkdir(parents=True, exist_ok=True)
    config = EvalConfig(
        tasks_path=args.data_root / "tasks.jsonl",
        snapshots_dir=args.data_root / "snapshots",
        results_dir=args.out,
        submission_dir=arm,
        models=_build_cli_model_registry(submission_dir=arm),
        image=args.image,
        sandbox="docker",
        timeout_seconds=int(ev.get("timeout_seconds", 300)),
        verification_timeout_seconds=int(ev.get("verification_timeout_seconds", 300)),
        max_time_minutes=max_time,
        max_tool_calls=int(ev.get("max_tool_calls", 100)),
        max_turns=int(turns) if turns is not None else None,
        limits=limits,
        generation_constraints=gen_constraints,
        adapter_manifest=discover_adapters(str(arm), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS),
        context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
        events_compaction_config=EventsCompactionConfig(
            compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5
        ),
        graph_dir=str(args.data_root / "graphs"),
        embeddings_dir=str(args.data_root / "embeddings"),
        wheels_dir=args.data_root / "wheels",
        task_ids=[args.task_id],
        concurrency=1,
        display_mode="quiet",
    )
    evaluator_cls = Evaluator
    if args.control:
        from adk_eval_core.tracing import SessionTrace

        class ControlEvaluator(Evaluator):
            async def _run_agent_sandbox(self, task, *a, **kw):
                patch = task.patch if args.control == "gold" else ""
                return patch, None, SessionTrace()

        evaluator_cls = ControlEvaluator
    started = time.time()
    result = asyncio.run(evaluator_cls(config).run())
    task = result.task_results[0] if result.task_results else None
    summary = {
        "task_id": args.task_id,
        "arm": arm.name,
        "endpoint": args.endpoint,
        "time_scale": args.time_scale,
        "effective_max_time_minutes": max_time,
        "wall_seconds": round(time.time() - started, 2),
        "resolved": bool(task and task.resolved),
        "status": getattr(task, "status", None),
        "error": getattr(task, "error_message", None),
        "patch_bytes": len(getattr(task, "agent_patch", "") or ""),
        "test_exit_code": getattr(task, "test_exit_code", None),
        "metrics": {
            k: getattr(task, k, None)
            for k in ("tool_calls", "total_llm_calls", "total_tokens", "duration_seconds")
        },
        "metadata": getattr(task, "metadata", None),
        "trace_path": getattr(task, "trace_path", None),
    }
    if task is not None:
        (args.out / "agent.patch").write_text(task.agent_patch or "")
        (args.out / "test_output.log").write_text(task.test_output or "")
    (args.out / "job_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str))


if __name__ == "__main__":
    main()
