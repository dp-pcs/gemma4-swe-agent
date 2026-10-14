"""Run a paired (sample x task x arm) evaluation matrix across vLLM endpoints.

Jobs are ordered by sample round, shuffled within a round with a fixed seed, so a
preempted run still holds a balanced partial comparison. Each job runs run_one.py
in its own process. Jobs whose job_summary.json exists are skipped (resume-safe).

Usage:
  python run_matrix.py --arms NAME=DIR [NAME=DIR ...] --task-file ids.txt \
      --samples 2 --endpoints URL[,URL] --workers-per-endpoint 6 \
      --data-root DIR --image TAG --out DIR [--time-scale 1.0] [--seed 0]
"""

import argparse
import json
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", nargs="+", required=True)
    ap.add_argument("--task-file", required=True, type=Path)
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--first-sample", type=int, default=0)
    ap.add_argument("--endpoints", required=True)
    ap.add_argument("--workers-per-endpoint", type=int, default=6)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--time-scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--job-timeout", type=int, default=3600)
    ap.add_argument("--reverse", action="store_true",
                    help="Take jobs from the end of the queue (for a second process on the same out dir)")
    args = ap.parse_args()

    arms = dict(a.split("=", 1) for a in args.arms)
    tasks = [t.strip() for t in args.task_file.read_text().split() if t.strip()]
    endpoints = args.endpoints.split(",")

    jobs = []
    for s in range(args.first_sample, args.first_sample + args.samples):
        round_jobs = [(s, t, a) for t in tasks for a in arms]
        random.Random(args.seed * 1000 + s).shuffle(round_jobs)
        jobs.extend(round_jobs)
    if args.reverse:
        jobs.reverse()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / ("matrix_reverse.json" if args.reverse else "matrix.json")).write_text(json.dumps({
        "arms": arms, "tasks": tasks, "samples": [args.first_sample, args.samples],
        "endpoints": endpoints, "workers_per_endpoint": args.workers_per_endpoint,
        "time_scale": args.time_scale, "seed": args.seed, "image": args.image,
    }, indent=2) + "\n")

    lock = threading.Lock()
    queue = list(jobs)
    done = {"n": 0, "resolved": {}}
    log = (args.out / "progress.log").open("a", buffering=1)

    def worker(endpoint: str) -> None:
        while True:
            with lock:
                if not queue:
                    return
                s, t, a = queue.pop(0)
            job_dir = args.out / f"s{s}" / a / t
            if (job_dir / "job_summary.json").exists() or (job_dir / "run.log").exists():
                continue
            job_dir.mkdir(parents=True, exist_ok=True)
            try:  # exclusive claim so concurrent matrix processes never share a job
                (job_dir / "claim").open("x").close()
            except FileExistsError:
                continue
            cmd = [sys.executable, str(HERE / "run_one.py"), "--arm-dir", arms[a], "--task-id", t,
                   "--data-root", str(args.data_root), "--image", args.image,
                   "--endpoint", endpoint, "--out", str(job_dir),
                   "--time-scale", str(args.time_scale)]
            started = time.time()
            with (job_dir / "run.log").open("w") as fh:
                try:
                    rc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                        timeout=args.job_timeout).returncode
                except subprocess.TimeoutExpired:
                    rc = "job_timeout"
            resolved = None
            if (job_dir / "job_summary.json").exists():
                resolved = json.loads((job_dir / "job_summary.json").read_text())["resolved"]
            with lock:
                done["n"] += 1
                key = f"s{s}/{a}"
                r = done["resolved"].setdefault(key, [0, 0])
                r[0] += bool(resolved)
                r[1] += 1
                log.write(json.dumps({"t": round(time.time()), "job": f"s{s}/{a}/{t}", "rc": rc,
                                      "resolved": resolved, "secs": round(time.time() - started),
                                      "done": done["n"], "remaining": len(queue),
                                      "tally": done["resolved"]}) + "\n")

    threads = [threading.Thread(target=worker, args=(ep,))
               for ep in endpoints for _ in range(args.workers_per_endpoint)]
    for th in threads:
        th.start()
        time.sleep(2)  # stagger container setup
    for th in threads:
        th.join()
    log.write(json.dumps({"finished": True, "tally": done["resolved"]}) + "\n")


if __name__ == "__main__":
    main()
