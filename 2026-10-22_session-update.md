# Session Update — 2026-10-22

Covers everything since the last written exchange (`2026-10-21_design-a-verdict-correction.md`): T3_5m's submission, rig calibration, the thinking-budget screen, Design A/P3's build, and a serving bug that cost most of the session to diagnose.

---

## 1. T3_5m submitted — ref 57504748, result pending

Built and uploaded as the scorer-safe hedge: worst case (every task hits the full 5-min cap) totals 300×120 + 120×4.75 setup + 214 startup = 10.2h, unconditionally under the 12h ceiling. Not a quality claim vs T3_7m (local net −3, p=0.55, not significant) — the point is it's the first config with a hard budget guarantee rather than one that happened to work.

## 2. Rig calibration: N=8 workers/endpoint matches L4's real speed

Swept local A100 concurrency 1–15 to find where per-stream decode matches L4's measured uncontended rate (34.3 tok/s). **N=8 → 33.6 tok/s**, the closest match. All screens through T3_5m ran at N=5 (37.0 tok/s), ~8% faster than the real scorer.

Re-screened T3_5m at the calibrated N=8: **24.6% resolved (28/114)** vs the N=5 result of 32.5%. The gap (8pp) is larger than the raw 8% speed difference because timeouts amplify — at the real scorer's pace, more tasks fail to finish before the 5-minute wall, not just finish slightly later. **Every local resolution-rate number we've quoted this project needs this correction applied before comparing to public scores.**

## 3. Thinking-budget screen: neutral

T3_5m (`thinking_budget=4096`) vs T3_5m_tc1536 (`=1536`), both at calibrated N=8, 38×3 each:

| | Resolved | Mean wall | Timeouts |
|---|---|---|---|
| tc4096 | 28/114 (24.6%) | 301.8s | 79 |
| tc1536 | 29/114 (25.4%) | 305.7s | 78 |

Net +1, p=1.0. At this operating point, wall-clock is the binding constraint, not token count — cutting thinking tokens doesn't free enough time to resolve more tasks. Using 1536 for P3 anyway since it's free and doesn't hurt.

## 4. Design A verdict reversal (recap) → P3 built

Previously reported NO-GO was wrong (truncating 7-min traces to estimate 5-min behavior doesn't model how the agent actually behaves when genuinely budgeted shorter — confirmed by truncating T3_7m at T3_5m's real token usage and getting 18.4% predicted vs T3_5m's actual 32.5%). Recomputed with T3_5m's real 3 samples: pass@3 oracle 39.5% (15/38) vs pass@1 28.9% (11/38) — clears the go/no-go bar.

**Built P3**: `SequentialAgent[locate, ParallelAgent[solver_a, solver_b, solver_c], selector]`.
- **locate** (≤2 calls): repro + SHELL_LOCATE shortlist, writes `/tmp/ctx.md`.
- **solvers** (≤7 calls each, identical prompts except worktree letter): own `git worktree add .wt/X`, edits only inside `.wt/X`, verifies with `PYTHONPATH=".wt/X:.wt/X/src:$PYTHONPATH"` (covers flat and src layouts without needing to know which applies in advance), writes `/tmp/cand_X.diff` + `.json`. No `submit_patch` tool.
- **selector** (≤3 calls, target 2): one fully-scripted Python block ranks candidates (verified > file-overlap agreement > smallest) and tries `git apply` on each in rank order automatically, then calls `submit_patch` immediately. Designed so the model only pastes one script and reads its output — minimizes risk around the harness's continuation-nudge mechanism, since `submit_patch()` breaks the loop immediately per the harness docs, so speed-to-submit is the actual safety mechanism.

Worktree mechanics (diff exclusion, patch apply) confirmed PASS on all 4 repos (requests = src-layout case) earlier this session.

## 5. Smoke test: PASS (structurally) — plus a serving bug that ate ~2 hours

Ran one real task through the full P3 tree. The multi-agent DAG compiled and executed correctly — all three solvers fired independently and made real tool calls, worktree setup ran. It timed out before any solver reached edit/verify (single eager-mode replica, serialized, not a performance test) — solvers over-explored past their call budget, a prompt-discipline issue, not a structural one.

**The real time sink:** after an earlier venv-pollution fix (unrelated worktree mechanics test accidentally ran `pip install -e .` inside the shared harness venv), the vLLM server appeared to hang indefinitely at a stable ~37GB GPU memory plateau with 0% utilization — survived a full VM reboot, looked identical every time. Root cause, found by testing `--enforce-eager` on a single replica (loads fast, surfaces real errors instead of silent non-response): `prometheus-fastapi-instrumentator==7.1.0` was incompatible with the newer `starlette==0.52.1` pulled in by the same fix — `AttributeError: '_IncludedRouter' object has no attribute 'path'` inside the instrumentator's routing middleware, crashing **every single HTTP request**, including the `/v1/models` health check used for readiness polling. The server was never hung — it was up and failing every request silently. Fixed by upgrading the instrumentator to 8.1.0.

**Takeaway for anyone else debugging this class of issue:** a vLLM server stuck at a stable GPU-memory plateau with 0% utilization isn't necessarily still loading — test with `--enforce-eager` on one replica/port first, since eager mode loads fast and will surface a real traceback instead of leaving you debugging what looks identical to a stuck model load.

## Open items / next steps

1. Tighten solver_a/b/c prompts: firmer call-count enforcement (stop exploring and edit by call 4), unambiguous worktree-only paths for edit/verify steps.
2. Confirm normal (non-eager, 4-replica, CUDA-graph-enabled) serving works with the instrumentator fix — not yet verified before the session's SSH-over-IAP connectivity became too unreliable to continue.
3. Run a real P3 vs T3_5m paired screen (38×3) once serving is confirmed.
4. Pin `prometheus-fastapi-instrumentator>=8.0.0` in any future venv-repair script.
