# Local Decode Benchmark + Design A Go/No-Go Gate

*Written 2026-10-21, in response to the second agent's suggested order (steps 2 and 3): run a like-for-like local decode benchmark, then gate Design A with a truncated best-of-3 analysis on existing traces. Both run this session.*

---

## 1. Local A100 decode benchmark (like-for-like with the L4 benchmark)

Same methodology as the L4 benchmark (~9.4K-token prompt, actual T3_7m system prompt, `thinking_budget: 4096`/`include_thoughts: true` matching our real sampling config), run against the local screening rig (TP=1 per A100 replica, port 8000).

**First three attempts were broken, not the hardware.** The streaming client only counted `delta.content`, but our system prompt drives the model straight into tool calls, so the real output lands in `delta.tool_calls[].function.arguments` — a channel the script wasn't reading. Non-streaming calls with `tools=[...]` declared surfaced the real numbers via `usage.completion_tokens`.

**Corrected result, 5 trials:**

| | tok/s |
|---|---|
| Local A100 (TP=1, uncontended) | **43.6** (median) |
| L4 (TP=4, uncontended, from the earlier benchmark) | 34.3 |

**This reverses the direction of the second agent's claim.** Clean single-stream, the local A100 is **~27% faster per token than L4**, not slower. The "~26 tok/s" figure the second agent cited (derived from `0.038 s/call` in real screening data) isn't a clean single-stream number — it's degraded by **5 concurrent workers sharing each A100 replica** in our actual screening setup (`run_matrix.py --workers-per-endpoint 5`). That contention, not raw chip speed, is why local screening timing looks slow relative to the scorer.

**Practical upshot:** the real scorer (one task at a time, no contention) likely *is* faster in wall-clock practice than our contended local screens suggest — same directional conclusion the second agent reached — but the fix is different. Rescaling caps by a tok/s hardware ratio would be wrong (and backwards). The right fix is to **reduce `workers-per-endpoint` in future screens** (toward 1) to remove the contention gap, not to inflate local token budgets.

---

## 2. Design A go/no-go: truncated best-of-3 analysis

Per the second agent's proposed gate: using the existing 684 runs (6 prompt arms × 38 held-out tasks × 3 samples, already in the repo), recompute pass@1 / pass@3 / naive-vote under a ~6,000-completion-token truncation — the per-solver budget implied by a 5-minute total cap once locate (~25s), selector (~30s), and margin (~30s) are subtracted, at ~30 tok/s.

Script: ad hoc, reads `job_summary.json` (resolved, patch_bytes) and `traces/trace_*.json` (`final_metrics.total_completion_tokens`) for every run under `results/harvest2_20261019/gates_v4/out_gates_v4/`.

**Results (T3_7m as the reference single-solver arm, 38 tasks):**

| Metric | Raw (no limit) | Truncated at 6,000 tokens |
|---|---|---|
| Pass@1 (T3_7m, sample 1) | 12/38 (31.6%) | 7/38 (18.4%) |
| Pass@3 (oracle: best of 3 samples) | 16/38 (42.1%) | 8/38 (21.1%) |
| Naive vote (smallest non-empty patch) | 15/38 (39.5%) | 8/38 (21.1%) |

**Token distribution across all 684 runs:** median 7,459, p75 9,447, p90 10,728, max 15,664. **72.2% of all runs (494/684) exceed 6,000 completion tokens.**

## Verdict: NO-GO for Design A at the 5-minute cap

The truncation collapses pass@3 from 16/38 to 8/38 — **identical to the truncated pass@1 (7/38, within noise)**. Running three parallel solvers at a ~6K-token budget each provides no measurable benefit over a single agent; most of the runs that currently resolve need more tokens than the budget allows regardless of how many parallel attempts are made. This matches the second agent's own stated failure condition ("if it collapses toward 13, the parallel design needs more time per solver than the budget allows") — it collapsed further, to 8.

For Design A to clear even the p75 token count (9,447, roughly where "most normally-resolving runs" sit), each solver needs ~315s, implying a total cap near 6.5 minutes — which is over the real 12h-budget-derived 5-minute ceiling. The gap doesn't close with cheaper locate/selector scripting or a tighter thinking cap alone; the solvers themselves need more wall-clock than the budget provides.

**Decision: build P-lite instead of Design A.** Parallel read-only analyzers (different localization strategies, no edits, no git worktrees) feeding a single T3_5m-capped solver. This captures some diversity benefit from running multiple localization strategies in parallel without hitting the per-solver token wall, since analyzer turns are short (reading + a verdict, not a full edit-verify loop).

## Open items this doesn't resolve

- The naive-vote simulation here used `patch_bytes` (smallest non-empty patch) as the selection signal, since job summaries don't store full diffs for a true "verified > diff-agreement > smallest" rule. A real P3/P-lite selector would have more signal (actual verification pass/fail per candidate) and might do better than this proxy suggests — this analysis is a lower bound on what a real selector could achieve, not a ceiling.
- `workers-per-endpoint` should be reduced in the next local screen (T3_5m was still run at 5) to get honest per-task timing before further cap-sensitive decisions.
