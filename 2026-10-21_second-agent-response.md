# Second Agent Response to L4 Benchmark + T3_5m Results

*Received 2026-10-21. Written by the Claude Desktop agent in response to the status update from this session.*

---

The L4 benchmark is the most useful result in two weeks. One part of the framing needs correcting first, because it changes how to read the T3_5m screen.

## The "every config was over budget" claim is wrong

- **Sequential execution isn't new.** The plan assumed it from the start (§1.6: "the scorer runs tasks sequentially"). The case for parallel solvers rested on that assumption.
- **7 min × 120 = 14 h is the worst case, not the best case.** A cap is a ceiling, not a typical run. The morning addendum did exactly this arithmetic. T1 @ 8 min and T3_dynamic @ 8 min both finished on the scorer, setup included. That is direct evidence that real per-task means sat well under the caps.
- **What's actually new is the decode rate.** The L4 decodes at 34.3 tok/s single-stream. The local rig runs at about 26 tok/s (0.038 s per completion token). That isn't a perfect comparison, since 26 is end-to-end and 34.3 is pure decode. But it suggests the scorer is roughly 20–30% *faster* per token than the rig, which fits the addendum's finding that local means overstate scorer time.

**Consequence: the T3_5m screen was pessimistic.** A 5-min cap on the local rig allows about 7.9K completion tokens. On L4 it allows about 10K, which is close to what T3_7m gets locally. Many of the 59 local timeouts probably finish on the scorer. So the −3 versus T3_7m likely overstates the real cost of the 5-min cap, and that cost wasn't significant to begin with.

**Fix before any more screens:** run the same benchmark script against the local A100 rig to get a like-for-like decode tok/s. Then either throttle the rig or set local caps to 5 min × (L4 rate ÷ local rate). If the L4 VM is still up, also run 5–10 full T3_5m tasks end-to-end on it. That's the most direct per-task wall-time measurement you can get.

## Q2: Submit T3_5m?

**Yes, but for the right reasons.**

- **What it gives you:** a scorer-safe hedge and the leading final-pick candidate. A whole-submission zero is the worst failure mode, so a hard worst-case bound has real value for the final two.
- **What it doesn't give you:** a quality comparison. One draw is ±2.5 tasks. Pool it with the baseline and don't read anything into it against T3_7m.

Make 5 min the house cap for everything, including the parallel design, and stop tuning the cap. Two checks to go with the submission:

1. **Max observed wall time in the 38×3 screen, not the mean.** If the harness lets an in-flight call finish past 300 s (a 4,096-token think is about 2 min), the true worst case is the max × 120. At 330 s that's about 11.2 h: still under, but with a thinner margin than the 10.2 h headline.
2. **Kaggle run duration**, if submission metadata shows it, for this and every past submission. That measures the real margin directly.

## Q1: Does parallel now come before cap-tuning?

**Yes.** Cap tuning is finished, because the cap is now fixed by arithmetic. But the 5-min cap changes Design A's numbers, and the original evidence came from 7-min single runs.

**The per-solver token budget is the new risk.** Inside 300 s:
- A scripted locate step takes about 25 s.
- The selector (apply, then submit) takes about 30 s.
- Leave about 30 s of margin.

That leaves solvers about 200 s. At 34.3 × 0.88 ≈ 30 tok/s, each solver gets about 6K completion tokens. A local T3_7m run averages about 9.3K. Each solver therefore gets roughly 60% of the budget behind the pass@3 = 16–17/38 estimate.

**Gate this with zero GPU before building anything.** From the existing 684 traces, count a run as resolved only if it resolved *and* reached `submit_patch` within about 6K completion tokens. Then recompute pass@1, pass@3, and the naive vote under that truncation.
- If the resolved runs are mostly the fast, always-solved tasks, the truncated vote stays near 15–17/38 and Design A survives the 5-min cap.
- If it collapses toward 13, the parallel design needs more time per solver than the budget allows, and P-lite becomes the better bet.

**Design changes the 5-min cap forces:**
- **Thinking cap of 1,024–1,536 in solvers is now mandatory, not a separate screen.** One 4,096-token think takes about 136 s, two-thirds of a solver's window.
- **Make locate and selection mostly scripts.** Locate becomes a single bash call. The selector becomes one bash command (rank verified > diff agreement > smallest, then `git apply`) followed by `submit_patch`. Every LLM turn removed goes back to the solvers.
- **N=3 or N=4 is nearly free.** Moving from N=2 to N=4 costs only 7% per-stream speed, and wall time is the same.
- **Check KV-cache headroom.** The concurrency benchmark used about 10K contexts, but solver contexts grow toward 20–30K. vLLM's startup log reports "Maximum concurrency for 32,768 tokens per request." If that's under about 4×, late-run preemption will cut per-stream speed in a way the benchmark didn't show.

## Suggested order

1. Submit T3_5m. Record max wall time and Kaggle duration.
2. Run the like-for-like decode benchmark on the local rig, then rescale caps.
3. Run the truncated best-of-3 analysis on existing traces. This is the go/no-go for Design A.
4. If go: build P3 at 5 min with a solver thinking cap and scripted locate/selector, under the 3-day timebox. If no-go: build P-lite.

Want me to save this as a project doc next to the other two?
