# P3 (Design A parallel-solver ensemble) screen — REJECTED, 2026-10-23

## Summary

P3 (`locate -> ParallelAgent[solver_a, solver_b, solver_c] -> selector`) was screened twice
against the existing T3_5m / T3_5m_tc1536 calibrated baseline data (38 held-out tasks x 3
samples = 114 runs). Both runs reject the design. No submission.

| Run | workers-per-endpoint | Resolved | vs T3_5m_tc1536 (29/114) | Root cause |
|---|---|---:|---|---|
| 1 | 8 (matched existing matrix) | 0/114 (0%) | W0/L28, net -28, p=0.0 | External contention: 1-7 tok/s decode |
| 2 (corrected) | 1 | 2/114 (1.8%) | W1/L27, net -26, p=0.0 | No per-sub-agent call budget enforcement |

## Run 1: contention artifact (invalid as a quality measurement)

`workers-per-endpoint=8` meant up to 8 concurrent P3 tasks per endpoint, each internally
spawning 3 concurrent solver streams -> ~24 concurrent LLM streams per GPU during the solver
phase, vs. the 3-stream concurrency P3 would see on the real sequential-evaluation scorer.
Measured solver decode rate during this run: **1.2-7.1 tok/s** (vs. 34.3 tok/s single-stream
target, and an expected ~30 tok/s at real 3-way concurrency per the L4 benchmark's N=3 scaling
measurement). Every one of 114 runs hit the 5-minute wall-clock without the selector stage
ever executing. See `diagnostic_traces/trace_fastapi_14258_w8_contention.json` for a concrete
per-call token-rate breakdown (step 9-23, 1.2-7.1 tok/s during solver phase).

This result says nothing about P3's design quality — it is a screening-infrastructure mismatch.
**Lesson for any future multi-stream-per-task design:** the existing matrix's `workers-per-endpoint`
calibration (N=8 matches L4's single-stream rate) was tuned for single-stream-per-task arms where
local inter-task concurrency simulates zero contention (matching the scorer's sequential
evaluation with 1 stream/task). A design with k concurrent streams per task needs
`workers-per-endpoint` set so that total concurrent streams per GPU ≈ k, not N calibrated for
k=1 silently multiplied by the design's internal fan-out.

## Run 2 (corrected concurrency): real design failure

With `workers-per-endpoint=1`, decode throughput recovered (solvers completed real tool calls),
but resolution dropped to 2/114 (1.8%) — far below T3_5m's 24.6%. Failure breakdown: timeout 70,
empty_patch 32, context 4, other_error 6 (vs. T3_5m: timeout 79, wrong_patch 7 — notably P3 has
far more empty patches and fewer wrong-but-complete ones). Mean tool calls 56.8 vs. T3_5m's 15.7
— more than double, despite P3's solver prompts explicitly budgeting 6-7 calls each plus 2 for
locate and 2-3 for the selector (expected total ~25-28).

**Root cause, confirmed from trace inspection** (`diagnostic_traces/trace_fastapi_14303_w1_solver_c_overrun.json`):
- `locate` used 3-4 tool calls despite its "at most 2 calls" hard limit (same failure mode seen
  in the original smoke test and in run 1's `trace_fastapi_13786_w8_locate_overrun.json`, where
  locate burned 3 debugging iterations on a syntax error and consumed 254 of 300 available
  seconds before any solver started).
- `ParallelAgent` genuinely runs solvers concurrently (confirmed: solver_a/b/c calls interleave
  within a few seconds of each other at the start) — the harness mechanism is not the problem.
- But one solver (`solver_c` in this trace) made **~20 tool calls**, running from step 12 (el=64s)
  to step 57 (el=311s) — nearly 5x its 7-call prose budget — while solver_a and solver_b finished
  on schedule around el=120-125s.
- `ParallelAgent` blocks until **all** sub-agents complete. One runaway solver therefore consumes
  the entire remaining wall-clock budget for the whole task, and the `selector` stage — which is
  the only stage with the `submit_patch` tool — never executes. The harness's own patch extraction
  grabbed whatever diff existed in `/workspace` at timeout (sometimes a solver's abandoned partial
  edit, scored as empty or wrong), not a selector-applied candidate.

**Why this differs from every single-agent arm (T1-T3_7m) that also had "soft prompt budgets":**
A single-agent arm's hard ceiling is `eval_config.yaml`'s session-wide `max_tool_calls` /
`max_time_minutes`, which bounds the one agent directly. P3's `eval_config.yaml` limits
(`max_tool_calls: 90`, `max_time_minutes: 5`) apply to the **whole SequentialAgent session**,
not to each sub-agent individually — there is no ADK mechanism found in this harness version to
cap `locate`'s or an individual solver's call count on its own. Prose instructions ("stop after
call 7") are demonstrably insufficient enforcement, as they have been for every arm in this
project's history, but for single-agent arms that just means somewhat late edits; for P3's
ParallelAgent stage, a single non-compliant sub-agent starves every other sub-agent in the same
round (including the two solvers that *did* finish on time) and permanently blocks the selector.

## Decision

**Reject P3 (Design A, parallel-solver ensemble). No submission.** The design requires either
(a) per-sub-agent hard call/time limits that this harness version does not appear to support via
`eval_config.yaml`, or (b) an architecturally different approach (e.g., a single agent that
tries multiple fixes sequentially with its own hard hard hard ceiling enforced by the one
session-level budget, forfeiting true concurrency). Neither is worth pursuing before the
deadline given T3_5m already clears a materially higher, well-understood bar (24.6% calibrated,
0/114 timeouts attributable to a structural flaw).

**T3_5m / T3_5m_tc1536 remain the best-validated local arms.** Return to single-agent prompt
refinement or accept T3_5m as the final prompt-only baseline for remaining Kaggle submissions.

## Cost and cleanup

VM `gemma-train2-20261016` (us-central1-f Spot a2-highgpu-4g) started ~21:44 UTC, stopped
~22:4x UTC after both runs and result collection — roughly 1 hour of 4x A100 Spot time
(~$10-12). VM stopped (not deleted), disk retained for future screens. No new GCP resources
created or left running.
