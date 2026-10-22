# Design A Verdict Correction — Check 1 Reverses NO-GO

*Written 2026-10-21, following the second agent's response (round 2) and executing their two proposed validation checks. Check 1 alone is decisive.*

---

## The check

The second agent proposed: truncate T3_7m's traces at T3_5m's **actual observed** per-run token budget (not the estimated 7.4K — used the real median of 6,501 from T3_5m's own trace data, which we now have) and compare the predicted resolve rate against T3_5m's real 37/114 (32.5%). If real >> predicted, the truncation method is too pessimistic and the NO-GO verdict is wrong.

**T3_5m token distribution (from 114 real traces):**
- Median: 6,501 tokens
- Mean: 6,034 tokens
- p75: 7,379 tokens
- Max: 8,803 tokens

## Check 1 result — method decisively falsified

| Truncation point applied to T3_7m traces | Predicted resolve rate |
|---|---|
| T3_5m median (6,501) | 18.4% (21/114) |
| T3_5m p75 (7,379) | 21.1% (24/114) |
| Original threshold (6,000) | 16.7% (19/114) |
| T3_5m actual max (8,803) | 22.8% (26/114) |

**T3_5m real resolve rate: 32.5% (37/114).** This is nearly double even the most generous truncation prediction. At T3_5m's own max token count (8,803 — no run exceeded this), the predicted rate is still only 22.8% vs the real 32.5%.

**The model adapts when actually configured for a shorter budget.** A trace generated under a 7-minute, 4,096-token-thinking budget does not predict what an agent does when told it has 5 minutes. The model uses tokens more efficiently, probably explores less in the thinking channel, and reaches action steps sooner. Truncating a long-budget trace is NOT a valid proxy for a properly-budgeted short-budget run.

## Design A pass@3 using real T3_5m samples

Rather than truncated estimates, using T3_5m's own three actual samples (s1/s2/s3) as a proxy for "three independent solver attempts at the 5-minute budget":

| Metric | Value |
|---|---|
| pass@1 (s1 only) | 11/38 = **28.9%** |
| pass@3 (oracle: any of 3 samples resolved) | 15/38 = **39.5%** |
| Naive vote (smallest non-empty patch) | 15/38 = **39.5%** |

This is substantially better than my truncation-based estimate (8/38 = 21.1%) and passes the original gate (the second agent's threshold was "if it collapses toward 13" as the NO-GO signal — 15/38 is well above 13/38).

## Important caveat on what this validates

The 15/38 pass@3 used three **independent**, **sequential-in-wall-clock** T3_5m runs (from our 38×3 screen, each with its own full 5-minute wall-clock budget). Design A runs 3 solvers **concurrently within a single 5-minute window**, with each solver starting ~25s into the run (after locate) and needing to leave ~30s for the selector — giving each solver roughly 215-245s instead of T3_5m's observed mean of 284s. Some discount from 15/38 is expected for this overhead.

That said, the truncation check proved the model adapts to tighter budgets more effectively than naive trace-cutting assumes, so the discount is probably smaller than one might naively estimate. The right next step is a real screen, not more estimates.

## Verdict correction: Design A → GO

**My earlier NO-GO (from `2026-10-21_local-decode-and-design-a-gate.md`) was wrong.** The methodology was flawed — truncating 7-minute traces doesn't predict 5-minute behavior. The real T3_5m data shows genuine diversity gain from ensembling (39.5% pass@3 vs 28.9% pass@1, +10.6pp). Design A should be built and screened, not ruled out from a broken proxy.

## Revised next steps

Per the second agent's recommendation, and incorporating this correction:

1. **T3_5m + thinking_budget=1536 screen** (cheapest lever, immediately actionable). If a 1536-token thinking cap reduces the 72%-of-runs-exceed-6K-tokens problem, the per-solver budget worry largely dissolves.
2. **Build P3 (Design A) under the 5-min cap** with the architecture fixes the second agent specified: scripted locate, concurrent ParallelAgent[solver, analyzer_1, analyzer_2] rather than sequential locate→solvers→selector, thinking cap 1536 in solvers, N=3 nearly free at 7% speed cost vs N=2.
3. **Submit T3_5m** to Kaggle in the next slot (scorer-safe, worst-case 10.2h under budget; first config with an unconditional bound).
