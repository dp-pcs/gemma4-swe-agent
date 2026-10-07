#!/usr/bin/env python3
"""
Apply ground-truth patch + test_patch to each task's snapshot (locally, no
docker) and run pytest scoped to ONLY the new/changed test function(s) from
test_patch. This isolates "does the fix actually work" from unrelated
pre-existing test flakiness/environment drift in the rest of the file
(which pollutes the full-file exit code the real harness uses).

Not a replacement for the docker-based harness -- it's a cleaner secondary
signal for local iteration, since we don't have Kaggle's exact pinned
test-dependency versions for the rest of each file's test suite.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEST_FUNC_RE = re.compile(r"^\+\s*(?:async\s+)?def (test_\w+)", re.MULTILINE)
TEST_CLASS_RE = re.compile(r"^\+?\s*class (Test\w+)", re.MULTILINE)


def extract_new_test_names(test_patch: str) -> list[str]:
    """Best-effort extraction of new/changed test function names from a unified diff."""
    return TEST_FUNC_RE.findall(test_patch)


def extract_test_files(test_patch: str) -> list[str]:
    files = []
    for line in test_patch.splitlines():
        if line.startswith("+++ b/"):
            files.append(line[6:].strip())
    return files


def run(cmd, cwd, timeout=60):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def verify_task_scoped(task: dict, snapshots_dir: Path) -> dict:
    instance_id = task["instance_id"]
    snapshot = snapshots_dir / f"{instance_id}.tgz"
    if not snapshot.exists():
        return {"instance_id": instance_id, "status": "no_snapshot"}

    test_names = extract_new_test_names(task["test_patch"])
    test_files = extract_test_files(task["test_patch"])
    if not test_names or not test_files:
        return {"instance_id": instance_id, "status": "no_new_tests_detected"}

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td) / "repo"
        workdir.mkdir()
        with tarfile.open(snapshot) as tf:
            tf.extractall(workdir)

        gt_patch = Path(td) / "gt.patch"
        test_patch = Path(td) / "test.patch"
        gt_patch.write_text(task["patch"] + "\n" if task["patch"] else "")
        test_patch.write_text(task["test_patch"] + "\n" if task["test_patch"] else "")

        if task["patch"].strip():
            r = run(["patch", "-p1", "--forward", "-i", str(gt_patch)], cwd=workdir)
            if r.returncode != 0:
                return {"instance_id": instance_id, "status": "gt_patch_apply_failed",
                        "detail": r.stdout[-500:] + r.stderr[-500:]}

        r = run(["patch", "-p1", "--forward", "-i", str(test_patch)], cwd=workdir)
        if r.returncode != 0:
            return {"instance_id": instance_id, "status": "test_patch_apply_failed",
                    "detail": r.stdout[-500:] + r.stderr[-500:]}

        # Critical: install the snapshot's OWN code editable, overriding whatever
        # version of this package is already in site-packages. Without this we'd
        # silently test the globally pip-installed library instead of the patched
        # snapshot -- which gives false signal (passes because upstream already
        # has the fix, or fails for unrelated upstream API drift).
        r = run([sys.executable, "-m", "pip", "install", "--no-deps", "-q", "-e", "."],
                cwd=workdir, timeout=120)
        if r.returncode != 0:
            return {"instance_id": instance_id, "status": "editable_install_failed",
                    "detail": r.stdout[-500:] + r.stderr[-500:]}

        node_ids = " or ".join(test_names)
        r = run(
            [sys.executable, "-m", "pytest", *test_files, "-k", node_ids, "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=workdir, timeout=90,
        )
        passed = r.returncode == 0
        return {
            "instance_id": instance_id,
            "status": "passed" if passed else "failed",
            "test_names": test_names,
            "exit_code": r.returncode,
            "tail": (r.stdout + r.stderr).strip().splitlines()[-6:],
        }


def main():
    tasks_path = ROOT / "competition_data" / "tasks.jsonl"
    snapshots_dir = ROOT / "competition_data" / "snapshots"
    repo_filter = sys.argv[1] if len(sys.argv) > 1 else None

    tasks = [json.loads(l) for l in tasks_path.open()]
    if repo_filter:
        tasks = [t for t in tasks if t["repo"].endswith(repo_filter)]
    available = {p.stem for p in snapshots_dir.glob("*.tgz")}
    tasks = [t for t in tasks if t["instance_id"] in available]

    print(f"Scoped-test verification of {len(tasks)} tasks (ground-truth patch, target tests only)\n")

    results = []
    for t in tasks:
        r = verify_task_scoped(t, snapshots_dir)
        results.append(r)
        mark = {"passed": "PASS", "failed": "FAIL"}.get(r["status"], r["status"].upper())
        print(f"  [{mark:^28}] {r['instance_id']}")
        if r["status"] not in ("passed",):
            for line in r.get("tail", []) or ([r["detail"]] if "detail" in r else []):
                print(f"      {line}")

    passed = [r for r in results if r["status"] == "passed"]
    print(f"\n{len(passed)}/{len(tasks)} tasks: ground-truth fix passes its own target test "
          f"({100 * len(passed) / len(tasks):.0f}%)")

    out = ROOT / "results" / "scoped_verify_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
