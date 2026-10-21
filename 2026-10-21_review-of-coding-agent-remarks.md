# Follow-up: review of the coding agent's remarks on the Oct 21 plan

Companion to `2026-10-21_deep-dive-and-improvement-plan.md`. Each remark was checked against the raw run data in `results/harvest2_20261019/gates_v4/out_gates_v4` (684 runs = 6 prompt arms × 38 tasks × 3 samples), the repo, and outside sources.

## Verdict summary

| # | Remark | Verdict | One-line reason |
|---|---|---|---|
| G1–G5 | Agreement points (Finding 04 is noise, thin proxy, get_status, parallel is new, replicate submissions) | **Valid** | No disagreement; G3 is now confirmed and strengthened (see P2). |
| P1 | Hardware mismatch should be priority zero | **Partly valid** | Calibration was done (9.05 s/call local vs 8.68 s/call on Kaggle 4×L4), and the scorer has validated our caps, so "every budget conclusion could be off" overstates it. But the calibration is weak (seconds per call, not tokens per second, done with a different prompt), so a single-stream L4 check should run first. |
| P2 | Spot-check get_status = 5/114 and union = 19/38 | **Valid request; both claims confirmed** | An independent raw grep reproduces both numbers exactly. A further check makes the "triage never fires" conclusion stronger, not weaker. |
| P3 | T5 = 38/114 (33.3%), net −2 vs T3_7m | **Accepted, not yet verifiable** | Matches the rundown, but no T5 outputs or HANDOFF entry are in the repo. Commit them. |
| P4 | Design A is a bigger lift than "all declarative" suggests | **Valid** | "No harness changes" is literally true, but the engineering risk was understated. Mitigation: a CPU-only mechanics test, a timebox and a fallback design (below). |
| P5 | Confirm the Nov 25 team-merger deadline and the Nov 12 paper track | **Confirmed by three independent secondary sources** | One more 1-minute check on Kaggle's Timeline tab is still worth doing. The same sources confirm the 12 h limit **includes sandbox setup**, which contradicts the sample `eval_config.yaml` comment. |

---

## P1 — Hardware mismatch (partly valid)

**Where the remark overstates:**
- Local timing was deliberately calibrated. `results/eval_matrix_20261014/RESULTS.md`: "Four A100 replicas, TP=1, 5 concurrent agents each. Measured **9.05 s per model call** cumulative, against the **8.68 s/call** a participant measured on Kaggle 4×L4 (discussion 746250)." The local rig was set up to be slightly *slower* than the scorer, not faster.
- The scorer itself has bracketed our budgets: T1 @ 8 min passed (local mean 398 s), T3_dynamic @ 8 min passed (ref 57449580, scored 0.13), and the v3 LoRA @ 8 min exceeded 12 h. So the 7-min T3_7m cap (local mean 352 s) sits inside a range the scorer has accepted. It is not a blind assumption.
- Paired arm-vs-arm comparisons (e.g. T3 vs T1) depend far less on absolute speed than on the cap itself.

**Where the remark is right:**
- The calibration matched **seconds per call**, measured with someone else's agent on Oct 14. Seconds per call depends on how many tokens each call emits. Our current prompt emits more tokens per call: T3_7m averages ~15 s/call (352 s / ~23 calls) against the 9 s/call calibration point. The right parity metric is **decode tokens per second**, and that has never been measured on L4.
- Only the *mean* was matched. Per-call distribution and prefix-cache behavior were not (RESULTS.md says so itself).
- **New fact: the 12 h limit includes sandbox setup** (see P5). The local rig times only the agent loop, so local mean time understates the scorer's per-task cost by however long setup takes on the hidden repos.
- The parallel design's case rests on L4 decode being memory-bound. The single-stream rate is the baseline for that claim.

**Action:** make the single-stream measurement explicit as step 0, in the same Kaggle 4×L4 session as the concurrency benchmark (it is the concurrency = 1 cell). Measure tokens/s and seconds/call with the T3_7m prompt and realistic ~10K-token contexts, plus container setup time for one task. Then rescale the local rig on **tokens/s**, not seconds/call. Cost: the same ~1 h session. It does not delay the parallel work.

---

## P2 — Spot-check of the two empirical claims (confirmed, and the conclusion strengthens)

Re-derived with a plain grep of the raw traces and job summaries, independent of the original script (commands in the appendix):

| Arm | get_status calls | Runs with ≥1 call | Runs |
|---|---:|---:|---:|
| T1_toolfix | 16 | 15 | 114 |
| T1_6m | 5 | 5 | 114 |
| T2_verify_6m | 6 | 6 | 114 |
| T3_dynamic_8m | 12 | 11 | 114 |
| **T3_7m** | **5** | **5** | **114** |
| T3_bail3 | 9 | 9 | 114 |

- **Union of resolved tasks across all 684 prompt-arm runs: 19/38** (also 19/38 when the LoRA arms are added).

**A fair objection to the original claim:** the model could triage without calling `get_status`, by counting its own calls. So I measured the *behavior*, not the tool call. The triage rule says: if not localized at the checkpoint, best-guess edit and **submit by call 11, within 4 minutes**.

| Arm | Runs that submitted by call 11 and ≤ 240 s |
|---|---:|
| T1_toolfix | 1 / 114 |
| T1_6m | 0 / 114 |
| T3_dynamic_8m | 0 / 114 |
| **T3_7m** | **1 / 114** |
| T3_bail3 | 1 / 114 (bail point was call 9 / 3 min) |

The early-submit path T3 was designed around happens in **≤1% of runs in every arm**, T3 included, and at the same rate as T1, which has no such rule. Whatever separates T3 from T1 (if anything does), it is not the triage branch. Likely candidates are the bounded fix/verify loop and the different wording around verification, or noise. Treat T3's design rationale as unproven. This also confirms the broader finding: the model does not follow budget-checkpoint instructions, so time discipline has to come from structure (separate agents, thinking caps), not prose.

---

## P3 — T5 result (accepted; please commit it)

- 38/114 = 33.3% matches the rundown's figure, so the number is consistent.
- It is **not in the repo**: no `T5_locate_7m` directory under `out_gates_v4`, no `gates_analysis_t5_*.json`, no HANDOFF entry. Last commit is still `f253c316 HANDOFF: T5 launch blocked by Spot stockout`.
- **Ask:** commit the T5 outputs (`s*/T5_locate_7m/`, both analysis JSONs), a HANDOFF entry with the paired W/L and p, and a note on the `run_matrix.py` resume bug and its fix (a resume bug can silently drop or duplicate jobs, so the fix should be reviewable).
- **What it changes in the plan:** the shortlist-as-a-prompt-step did not help on familiar repos (net −2, n.s.). Idea C (localization) moves down. Keep SHELL_LOCATE only as an optional shared pre-step inside the parallel design, and test it on the unfamiliar-repo proxy, where the model can't rely on prior knowledge of the layout. Don't spend a standalone screen on it.

---

## P4 — Engineering lift of Design A (valid)

"No harness changes" was literally accurate: everything compiles from YAML (`adk_submission` supports `ParallelAgent`/`SequentialAgent`, and budgets are ours in `eval_config.yaml`). But the plan understated the debugging risk. Three concrete risks, each with a cheap way to retire it **before** any GPU time:

| Risk | Retire it with | GPU? |
|---|---|---|
| Worktree + import path. `git worktree` inside `/workspace`, `.wt/` excluded from the diff, and tests importing the worktree copy rather than the editable install at `/workspace`. | Script over all 15 local snapshots in the sandbox image: create `.wt/a`, make a trivial edit, run one test with `PYTHONPATH`, confirm the import path, `git apply` the diff into `/workspace`, confirm `.wt/` is absent from `git add -N . && git diff HEAD`. **requests uses `src/` layout** (`src/requests/__init__.py`; FastAPI is flat), so it is a ready-made src-layout case. | No |
| Nudge re-runs the whole `SequentialAgent` (the harness sends a continuation message if the root ends without `submit_patch`; ADK re-enters the root from the first sub-agent). | Selector applies the best patch to `/workspace` and calls `submit_patch` **first**, then may refine. Verify with a 2-task run where the selector is told not to submit. | 1 short run |
| Shared clock and budgets across branches. | `eval_config`: `max_tool_calls` ~120, `max_turns` ~250. Solvers stop on wall-clock (`date +%s` vs a start stamp written by the locate stage), not on `get_status`, since P2 shows the model ignores checkpoint instructions. | No |

**Timebox:** 3 working days for Design A mechanics. If they are not clean by then, fall back to **P-lite**: a `ParallelAgent` of 2–3 *read-only* analyzers (different localization strategies, no edits, so no worktrees), followed by the single T3 solver. It captures part of the diversity benefit with none of the workspace risk.

---

## P5 — Dates and paper track (confirmed by secondary sources)

Kaggle's own pages are JavaScript-rendered and could not be fetched directly. Three independent sources agree:
- **Nov 12** — optional research-paper deadline; separate **$35K** pool ($15K best paper, $10K best new resource, $10K best new application). The paper competition page exists at kaggle.com/competitions/gemma-4-developer-agent-paper.
- **Nov 25** — entry deadline (accept rules) **and team-merger deadline**.
- **Dec 2** — final submission deadline; main track $65K ($37K / $18K / $10K); 2 final submissions.
- **12 h runtime limit is "inclusive of sandbox setup time, but excluding time for patch validation."** This contradicts the sample `eval_config.yaml` comment ("Container setup is excluded"), so plan to the stricter reading.

Sources: [sweeden-ttu/developer-agent](https://github.com/sweeden-ttu/developer-agent) (quotes Kaggle's timeline and runtime text), [nymrel-swarm-studio issue #20](https://github.com/nymrel/nymrel-swarm-studio/issues/20), [AI Wiki summary](https://aiwiki.ai/wiki/gemma_4_developer_agent_competition). One-minute confirmation: the Kaggle competition's **Timeline** section.

---

## Revised Week 1 (Oct 21–27)

| Order | Step | Gate |
|---|---|---|
| 0 | **Housekeeping:** commit T5 outputs + HANDOFF entry + resume-bug note; confirm dates on Kaggle's Timeline tab. | Done |
| 1 | **Kaggle 4×L4 session:** (a) single-stream tokens/s and seconds/call with the T3_7m prompt at ~10K context, plus one task's container setup time; (b) concurrency 2/3/4 on the same prompts; (c) whether prefix caching is active. | (a) recalibrates the local rig on tokens/s. (b) per-stream decode at concurrency 3 ≥ 75% of single → proceed. |
| 2 | **CPU-only mechanics test** of worktrees / imports / diff exclusion across all 15 snapshots (requests = src-layout case). Can run in parallel with step 1. | 15/15 clean, or a documented per-layout fix |
| 3 | Rescale the local rig to step 1's tokens/s and re-check that T3_7m's local mean time still fits the 12 h ceiling **including setup**. | Mean (agent + setup) × 120 ≤ ~10.5 h |
| 4 | Build P3 (Design A) under a **3-day timebox**; 5-task smoke incl. the no-submit nudge test. | Mechanically clean, else switch to P-lite |
| 5 | Screen P3 (or P-lite) vs T3_7m, 38×1 then 38×3 paired. | Net ≥ +6 / 114 → candidate |

Weeks 2–6 are unchanged from the plan, except: idea C (shortlist) moves down per P3; budget rules are rewritten as structure rather than prose per P2; and paper-track and team-merger decisions go on the calendar for Nov 5 and Nov 20.

---

## Appendix — spot-check commands (run from `results/harvest2_20261019/gates_v4/out_gates_v4`)

```bash
# get_status calls / runs with a call / runs, per arm
for a in T1_toolfix T1_6m T2_verify_6m T3_dynamic_8m T3_7m T3_bail3; do
  c=$(cat s*/$a/*/traces/*.json | grep -o '"function_name": "get_status"' | wc -l)
  r=$(grep -l '"function_name": "get_status"' s*/$a/*/traces/*.json | wc -l)
  n=$(ls s*/$a/*/traces/*.json | wc -l); echo "$a $c $r $n"; done

# union of tasks resolved by any prompt-arm run
for a in T1_toolfix T1_6m T2_verify_6m T3_dynamic_8m T3_7m T3_bail3; do
  grep -l '"resolved": true' s*/$a/*/job_summary.json; done | awk -F/ '{print $3}' | sort -u | wc -l
```

Early-submit behavior check (triage path): for each trace, count non-`get_status` tool calls before the first `submit_patch` and read that call's `extra.elapsed_s`; a run counts if it submitted at call ≤ 11 and ≤ 240 s.

---

## Addendum (12:54 MT) — primary-source check and runtime reconciliation

**Confirmed from Kaggle's Overview page (checked in the browser):** Nov 12 paper deadline ($35K Paper Submission Award), Nov 25 entry and team-merger deadline, Dec 2 final submission deadline, all 23:59 UTC. The Evaluation section says the 12 h limit covers "all tasks, inclusive of sandbox setup time, but excluding time for patch validation." The strict reading is official. The harness README's per-task timer and the 12 h total are separate budgets, so both statements are true.

**The runtime arithmetic, done carefully:**
- A naive projection from local means says T3_7m ≈ 352 s × 120 = 11.7 h before setup, and T1 @ 8 min ≈ 398 s × 120 = 13.3 h, which would be over budget.
- But **T1 @ 8 min (ref 57277262) and T3_dynamic @ 8 min (ref 57449580) both completed on the scorer**, setup included. With ~120 tasks, the scorer's real mean was therefore ≤ 360 s per task *including setup*, while the local means were 398 s and 370 s *excluding setup*. So **local means overstate scorer time by at least ~10–15%** for these configs. That is consistent with the local rig being calibrated slightly slower per call (9.05 vs 8.68 s) and with hidden-task runs differing from FastAPI/Rich ones.
- So "T3_7m is over budget" does not follow. T3_7m has a lower cap (7 vs 8 min) and a lower local mean (352 s) than two configs the scorer finished. By direct comparison it is safer than both.
- What is right in the warning: we know **that** those runs finished, not **by how much**. The margin is unmeasured, and only the v3 LoRA run (8 min, local mean 409 s plus adapter overhead) tells us roughly where the edge is. A timeout scores nothing, so the margin matters most for the two **final** picks.

**Decisions:**
1. Plan to the strict reading (setup counts). *Agreed.*
2. Day-to-day public submissions: a 7-min cap is acceptable, since it sits inside proven territory. **Final two picks: cap at 6–6.5 min** unless the margin has been measured. T1 @ 6 cost nothing locally (35 vs 33/114), so the insurance is cheap. *Partly agreed.*
3. Measure the margin rather than guess it: in the Week-1 Kaggle 4×L4 session, time container setup for a few local tasks (FastAPI, Rich, requests) and add it to the tokens/s rescaling (step 3 of the revised Week 1). If Kaggle's submission metadata exposes run duration, record it for every past submission. That is the most direct margin measurement available.
4. Don't edit the Kaggle-provided `competition_data/sample_submission/eval_config.yaml`. It is a reference file and nothing reads its comment. Record the official rule in HANDOFF/AGENTS instead. Our own `eval_config.yaml` files carry no such comment. *Not agreed, low stakes.*
5. Hidden task count: "~120, split equally between public and private" (rundown: 58 public, ~58–62 private). The exact private count is undisclosed. *Unchanged.*
6. Committing T5 outputs, the HANDOFF entry and the resume-bug note is independent of all this. *Agreed — go ahead.*
