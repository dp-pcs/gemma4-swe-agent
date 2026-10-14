"""Summarize a run_matrix output directory: per-arm rates and paired tests vs a baseline arm.

Usage: python3 analyze.py OUT_DIR [--baseline A_recipe] [--json report.json]
"""

import argparse
import json
from collections import defaultdict
from math import comb
from pathlib import Path


def sign_test(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2**n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--baseline", default="A_recipe")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    rows = {}  # (sample, arm, task) -> summary
    for p in args.out.glob("s*/*/*/job_summary.json"):
        s, arm, task = p.parts[-4], p.parts[-3], p.parts[-2]
        rows[(s, arm, task)] = json.loads(p.read_text())

    arms = sorted({a for _, a, _ in rows})
    report = {"arms": {}, "paired_vs_baseline": {}}
    for arm in arms:
        rs = [r for (s, a, t), r in rows.items() if a == arm]
        n = len(rs)
        secs = [r["metrics"].get("duration_seconds") or r["wall_seconds"] for r in rs]
        errors = defaultdict(int)
        for r in rs:
            if not r["resolved"]:
                e = (r.get("error") or "").lower()
                key = ("timeout" if "time" in e else "context" if "context" in e or "token" in e
                       else "empty_patch" if r["patch_bytes"] == 0 else "wrong_patch" if not e else "other_error")
                errors[key] += 1
        report["arms"][arm] = {
            "runs": n,
            "resolved": sum(r["resolved"] for r in rs),
            "rate": round(sum(r["resolved"] for r in rs) / n, 3) if n else None,
            "mean_task_seconds": round(sum(secs) / n, 1) if n else None,
            "mean_tool_calls": round(sum(r["metrics"].get("tool_calls") or 0 for r in rs) / n, 1) if n else None,
            "failures": dict(errors),
        }

    base = args.baseline
    for arm in arms:
        if arm == base:
            continue
        wins = losses = both = neither = 0
        for (s, a, t), r in rows.items():
            if a != arm or (s, base, t) not in rows:
                continue
            b = rows[(s, base, t)]["resolved"]
            c = r["resolved"]
            wins += c and not b
            losses += b and not c
            both += b and c
            neither += not b and not c
        report["paired_vs_baseline"][arm] = {
            "pairs": wins + losses + both + neither, "wins": wins, "losses": losses,
            "net": wins - losses, "sign_test_p": round(sign_test(wins, losses), 4),
        }

    # Baseline self-agreement across samples estimates sampling noise.
    by_task = defaultdict(dict)
    for (s, a, t), r in rows.items():
        if a == base:
            by_task[t][s] = r["resolved"]
    samples = sorted({s for (s, a, _) in rows if a == base})
    if len(samples) >= 2:
        s0, s1 = samples[:2]
        common = [t for t in by_task if s0 in by_task[t] and s1 in by_task[t]]
        flips = sum(by_task[t][s0] != by_task[t][s1] for t in common)
        report["baseline_flips"] = {"tasks": len(common), "flipped": flips}

    print(json.dumps(report, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
