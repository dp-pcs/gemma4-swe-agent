# Scorer-parity screen of the public recipe and three single-variable variants — 2026-10-14

## What was done

Submitted the public 0.24 recipe to Kaggle as **ref 57163806** (sha256
`a9d2a86d759299fdca9cd8010aac3636f9fd3f39c5325ea992cf99806f8e935a`), built from
`honghanhhh/gemma-4-baseline-lb-0-24` by parsing the notebook's `FILES` literal
(`scripts/build_from_notebook.py`; the notebook was never executed). Score pending at the
time of writing; check `kaggle competitions submissions -c gemma-4-developer-agent`.

Then ran a local screen of that recipe plus three one-variable changes.

## Result: no variant beat the recipe by a detectable margin

95 tasks, one sample per arm, paired on identical tasks.

| Arm | Change from the submitted recipe | Resolved /95 | Paired vs A (W/L) | Sign test p | Mean task s |
| --- | --- | ---: | :---: | ---: | ---: |
| A_recipe | — (ref 57163806 bytes) | 37 (38.9%) | — | — | 329.7 |
| B_temp1 | `temperature` 0.2→1.0, `top_k: 64` | 35 (36.8%) | 4 / 6 | 0.75 | 326.3 |
| C_think2k | `thinking_budget` 4096→2048 | 38 (40.0%) | 6 / 5 | 1.00 | 310.0 |
| D_editrecover | one prompt line: shell fallback after 2 rejected `edit_file` calls | 39 (41.1%) | 7 / 5 | 0.77 | 318.2 |

Every difference is well inside noise. **No promotion is warranted; the incumbent submitted
bytes are unchanged.** C and D are each slightly ahead and change the failure mix in the
intended direction (C: timeouts 19→8; D: timeouts 19→11, no `other_error` loops), which makes
them reasonable candidates for a repeat run, not for a submission on this evidence.

B is worth noting because two public sweeps reported temperature 1.0 as a gain of 3–4 tasks.
It did not reproduce here (-2 tasks, 4W/6L). Do not spend a submission on temperature.

Failure mix (counts of the 95 runs):

| Arm | wrong patch | timeout | empty patch | other error |
| --- | ---: | ---: | ---: | ---: |
| A | 28 | 19 | 7 | 4 |
| B | 30 | 15 | 11 | 4 |
| C | 42 | 8 | 7 | 0 |
| D | 34 | 11 | 9 | 2 |

Across all arms the largest single bucket is a non-empty patch that fails the hidden tests
(28–42 of 95). Budget tuning cannot fix those; they are issue-comprehension failures.

## Measurement setup (differs from earlier sessions)

- **Scorer-parity config, not 64K.** vLLM `max_model_len=32768`, and ADK
  `EventsCompactionConfig(15, 2, 14336, 5)` + `ContextCacheConfig(2048, 1800, 10)` exactly as
  the 2026-10-12 starter notebook builds them. Earlier local screens used a 64K context and no
  compaction, so they could not observe the scorer's context behavior. Zero context-overflow
  failures occurred here.
- **Latency calibrated to Kaggle.** Four A100 replicas, TP=1, 5 concurrent agents each. Measured
  **9.05 s per model call** cumulative, against the 8.68 s/call a participant measured on Kaggle
  4×L4 (discussion 746250). Per-task time budgets are therefore roughly comparable to the scorer's.
- **95 tasks, one process per task.** Start from the 114 sound tasks in the public audit
  (dmitriigluzdov, CC BY 4.0), keep FastAPI+Rich (one sandbox profile), then drop 11 whose gold
  patch did not pass in our image: `fastapi_14962 14964 15785 15763`, `rich_3296 3469 3472 3782
  3942 4070 4079`. Controls for all 106: gold resolves 95, and the two smoke-tested empty-patch
  controls fail.
- **Interleaved and resumable.** Jobs shuffled within a sample round under a fixed seed, two
  queue processes claiming jobs exclusively from opposite ends, so a preemption leaves a balanced
  partial comparison. The Spot VM was preempted once at 04:16 UTC; 20 incomplete jobs were
  deleted and re-run from scratch, 135 completed ones kept.

## Limits

- **One sample per arm.** With 95 tasks, a one-sample paired screen only detects large effects.
  Public data says ~15% of tasks flip between identical repeated runs, so a ±2 task difference
  carries no information. Two or three samples per arm are needed for a real 4–5 task test.
- Public FastAPI/Rich tasks, not the hidden private repositories. Staff state no public repo
  appears in the hidden set.
- 4×A100 TP=1 with 5 concurrent agents, not 4×L4 TP=4 sequential. Latency was matched on average;
  per-call distribution and prefix-cache behavior were not.
- The 11 excluded tasks are an image-specific gold failure, not necessarily unsound tasks.

## Cost and cleanup

4×A100 Spot in us-central1-c, **2.59 GPU-hours** across two runs (preemption in between),
roughly **$13** of the authorized $100. Plus about 1.2 CPU-hours on an e2-standard-16 for the
environment build and controls.

Created and then deleted: VM `gemma-matrix-20261014-cpu`/`-gpu`, disk
`gemma-matrix-20261014-disk`, snapshot `gemma-matrix-20261014-snap`. Prefix-filtered instance,
disk and snapshot lists are empty. Original VM `gemma-agent-dev` (id 8178724251330271494)
remains TERMINATED and its 300GB disk (id 7820791868839024902) READY. Runtime is not settled
billing.

## Artifacts

- `out/s0/<arm>/<task>/` — `job_summary.json`, `agent.patch`, `test_output.log`, `traces/`.
- `controls/gold/<task>/` and `controls.log` — the gold-patch control for all 106 candidates.
- `tasks_95.txt`, `tasks_106.txt`, `task_soundness.csv` (+ `LICENSE.txt`, `SOUNDNESS_SOURCE.txt`).
- `arms/` — the exact four submission trees; `serving_requirements.lock` — 248 hash-pinned wheels.
- `matrix_*.tgz` + `artifacts.sha256`; runner sources in `scripts/eval_matrix/`.

## Next

1. Repeat A/C/D at 2–3 samples each before considering any promotion. Budget about 3 GPU-hours
   per additional full sample of one arm.
2. The dominant failure is a wrong non-empty patch, so look there, not at budgets. The traces in
   `out/s0/*/` now contain 380 graded runs for exactly that analysis.
3. Those 380 runs (with 149 resolved) are also the first real corpus of Gemma-generated
   successful trajectories available for fine-tuning.
