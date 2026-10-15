"""Deterministic train/held-out split of task ids, stratified by repository prefix.

The held-out set must never contribute trajectories to training (T3b gate G3), and no
trace from a held-out task — from any run or arm — may be used either.

Usage: python3 -I split_tasks.py tasks.txt OUT_DIR [--heldout-frac 0.4] [--seed 20261015]
"""

import argparse
import collections
import random
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--heldout-frac", type=float, default=0.4)
    ap.add_argument("--seed", type=int, default=20261015)
    args = ap.parse_args()

    tasks = sorted(t for t in args.tasks.read_text().split() if t.strip())
    by_repo = collections.defaultdict(list)
    for t in tasks:
        by_repo[t.rsplit("_", 1)[0]].append(t)
    rng = random.Random(args.seed)
    train, heldout = [], []
    for repo in sorted(by_repo):
        ids = sorted(by_repo[repo])
        rng.shuffle(ids)
        k = round(len(ids) * args.heldout_frac)
        heldout += ids[:k]
        train += ids[k:]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "train_tasks.txt").write_text("\n".join(sorted(train)) + "\n")
    (args.out_dir / "heldout_tasks.txt").write_text("\n".join(sorted(heldout)) + "\n")
    per_repo = {r: (sum(t in train for t in by_repo[r]), sum(t in heldout for t in by_repo[r])) for r in by_repo}
    print(f"train {len(train)}  heldout {len(heldout)}  seed {args.seed}  per repo (train, heldout): {per_repo}")


if __name__ == "__main__":
    main()
