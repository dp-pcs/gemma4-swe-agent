"""Summarize a run_gates.sh output directory: G1 per-task table and the held-out screen.

Usage: python3 -I gates_report.py OUT_GATES_DIR [--base-counts harvest_counts.json]
The optional JSON maps task_id -> number of harvest successes out of 6 for the untrained agent.
"""

import argparse
import collections
import glob
import json
import math
import os


def load(out, sample, arm):
    rows = {}
    for js in glob.glob(os.path.join(out, sample, arm, "*", "job_summary.json")):
        j = json.load(open(js))
        rows[j["task_id"]] = j
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--base-counts")
    args = ap.parse_args()
    base = json.load(open(args.base_counts)) if args.base_counts else {}

    g1 = load(args.out, "s0", "G1_lora")
    if g1:
        print(f"G1 (adapter only), {len(g1)} tasks:")
        for t, j in sorted(g1.items()):
            print(f"  {t:<16} base {base.get(t, '?')}/6  adapter {'RESOLVED' if j['resolved'] else 'failed  '}  "
                  f"calls={j['metrics']['tool_calls']:>2} wall={j['wall_seconds']:>4.0f}s patch={j['patch_bytes']:>5}")
        print(f"  resolved {sum(j['resolved'] for j in g1.values())}/{len(g1)}")

    samples = sorted(d for d in os.listdir(args.out) if d.startswith("s") and d != "s0")
    if not samples:
        return
    per = collections.defaultdict(dict)  # task -> sample -> (t1, g1)
    for s in samples:
        t1, g = load(args.out, s, "T1_toolfix"), load(args.out, s, "G1_lora")
        for t in set(t1) | set(g):
            per[t][s] = (t1.get(t, {}).get("resolved"), g.get(t, {}).get("resolved"))
    tot_t1 = tot_g1 = n_t1 = n_g1 = 0
    wins = losses = 0
    print(f"\nHeld-out screen, samples {samples}:")
    for s in samples:
        a = sum(1 for t in per if per[t].get(s, (None, None))[0]); na = sum(1 for t in per if per[t].get(s, (None, None))[0] is not None)
        b = sum(1 for t in per if per[t].get(s, (None, None))[1]); nb = sum(1 for t in per if per[t].get(s, (None, None))[1] is not None)
        print(f"  {s}: T1 {a}/{na}  G1_lora {b}/{nb}")
        tot_t1 += a; n_t1 += na; tot_g1 += b; n_g1 += nb
        for t in per:
            x, y = per[t].get(s, (None, None))
            if x is None or y is None:
                continue
            wins += (y and not x); losses += (x and not y)
    n = wins + losses
    p = min(1.0, sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) * 2 / 2 ** n) if n else 1.0
    print(f"  totals: T1 {tot_t1}/{n_t1} ({100*tot_t1/max(n_t1,1):.1f}%)  G1_lora {tot_g1}/{n_g1} ({100*tot_g1/max(n_g1,1):.1f}%)")
    print(f"  paired G1_lora vs T1: W {wins} / L {losses}  net {wins-losses}  sign-test p {p:.4f}")
    flips = collections.Counter()
    for t in per:
        for s, (x, y) in per[t].items():
            if x is not None and y is not None and x != y:
                flips["adapter_only" if y else "base_only"] += 1
    print(f"  discordant runs: {dict(flips)}")


if __name__ == "__main__":
    main()
