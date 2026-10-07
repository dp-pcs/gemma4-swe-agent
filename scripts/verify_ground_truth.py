#!/usr/bin/env python3
"""
Run Phase 2 verification (Docker sandbox + pytest) on tasks using their
ground-truth patches. Confirms each task is actually solvable and exercises
the full sandbox/patch-apply/test pipeline without needing any LLM.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from adk_eval_core.tracing import SessionTrace
from adk_submission import ModelRegistry

from swegemma.config import EvalConfig
from swegemma.deduplication import resolve_task_snapshot_paths
from swegemma.harness.verification import verify_task
from swegemma.models import load_tasks
from swegemma.sandbox import ContainerConfig, ContainerManager

ROOT = Path(__file__).parent.parent


async def verify_one(docker, config, task, sem) -> dict:
    async with sem:
        snapshot_path, base_snapshot_path, patch_path = resolve_task_snapshot_paths(
            config.snapshots_dir, task.instance_id, task.repo
        )
        if not snapshot_path.exists():
            return {
                "instance_id": task.instance_id,
                "repo": task.repo,
                "resolved": False,
                "test_exit_code": -1,
                "error": f"snapshot not found: {snapshot_path}",
                "elapsed_s": 0.0,
            }

        t0 = time.perf_counter()
        result = await verify_task(
            docker,
            config,
            task,
            snapshot_path,
            base_snapshot_path=base_snapshot_path,
            patch_path=patch_path,
            agent_patch=task.patch,  # ground-truth fix, not an agent output
            agent_error=None,
            trace=SessionTrace(),
            start_time=t0,
        )
        elapsed = time.perf_counter() - t0
        return {
            "instance_id": task.instance_id,
            "repo": task.repo,
            "resolved": result.resolved,
            "test_exit_code": result.test_exit_code,
            "error": result.error,
            "elapsed_s": round(elapsed, 1),
        }


async def main(args):
    tasks_path = ROOT / "competition_data" / "tasks.jsonl"
    snapshots_dir = ROOT / "competition_data" / "snapshots"
    results_dir = ROOT / "results" / "ground_truth_verify"
    results_dir.mkdir(parents=True, exist_ok=True)

    all_tasks = load_tasks(tasks_path)
    if args.repo:
        all_tasks = [t for t in all_tasks if t.repo.endswith(args.repo)]

    available = {p.stem for p in snapshots_dir.glob("*.tgz")}
    tasks = [t for t in all_tasks if t.instance_id in available]

    if not tasks:
        print(f"No tasks with local snapshots found in {snapshots_dir}.")
        return

    print(f"Verifying {len(tasks)} tasks with ground-truth patches (docker sandbox)...\n")

    config = EvalConfig(
        tasks_path=tasks_path,
        snapshots_dir=snapshots_dir,
        results_dir=results_dir,
        submission_dir=ROOT / "competition_data" / "sample_submission",
        models=ModelRegistry(),
        image="swebench-sandbox:local",
        sandbox="docker",
        timeout_seconds=120,
        graph_dir=str(ROOT / "competition_data" / "graphs"),
        embeddings_dir=str(ROOT / "competition_data" / "embeddings"),
    )
    docker = ContainerManager(ContainerConfig(image=config.image, timeout_seconds=120))

    sem = asyncio.Semaphore(args.concurrency)
    results = []
    for coro in asyncio.as_completed([verify_one(docker, config, t, sem) for t in tasks]):
        r = await coro
        status = "RESOLVED" if r["resolved"] else "FAILED  "
        print(f"  [{status}] {r['instance_id']:<30} {r['elapsed_s']:5.1f}s"
              + (f"  -- {r['error']}" if r["error"] else ""))
        results.append(r)

    resolved = [r for r in results if r["resolved"]]
    failed = [r for r in results if not r["resolved"]]

    print(f"\n{'=' * 60}")
    print(f"Results: {len(resolved)}/{len(tasks)} resolved "
          f"({100 * len(resolved) / len(tasks):.0f}%)")
    if failed:
        print(f"\nFailed/unresolved tasks ({len(failed)}):")
        for r in failed:
            print(f"  {r['instance_id']}: {r['error'] or 'pytest exit code ' + str(r['test_exit_code'])}")

    out = results_dir / "summary.json"
    out.write_text(json.dumps({
        "total": len(tasks),
        "resolved": len(resolved),
        "resolution_rate": len(resolved) / len(tasks),
        "tasks": results,
    }, indent=2))
    print(f"\nFull results saved to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None,
                        help="Filter by repo suffix, e.g. 'requests' or 'fastapi'")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Parallel docker containers (default: 2)")
    args = parser.parse_args()
    asyncio.run(main(args))
