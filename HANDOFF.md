# Session handoff — 2026-10-15

## Where we stopped

Ref 57163806 (the earlier honghanhhh prompt) scored **0.15 = 9/58 public tasks**: above the 0.12
incumbent, below the field's plateau. No new submission was made this session. It produced the
failure anatomy of the 380 preserved runs, byte-exact reconstructions of the two current public
recipes, and the experiment plan below, whose goal is 0.30 (= 18/58).

## Facts established this session

- **Public LB = 58 tasks, score = floor(k/58 × 100)/100.** All 14 distinct scores across 2,809
  teams lie on that lattice (0.01, 0.03, 0.05, 0.06, 0.08, 0.10, 0.12, 0.13, 0.15, 0.17, 0.18,
  0.20, 0.22, 0.24); two public notebooks reach the same conclusion independently. Leaders: 14/58
  (0.24, 2 teams); 13/58 (0.22, 19 teams); 12 (0.20, 57); 11 (0.18, 215). **0.30 requires 18/58**
  (17 displays as 0.29). Hidden tasks come from private repositories, none of the four public ones.
- **Identical bytes vary by SD ≈ 2 tasks** (public ledgers: 5→4, 5→4, 5→8 near-identical; ours
  0.08→0.12 = 5→7). One submission cannot resolve a ±2-task change.
- **Our submitted prompt is a superseded revision.** honghanhhh's notebook is now "v3" =
  flexonafft `budget-aware-coding-agent-v2` (the 0.22 cluster's recipe) + three prompt edits
  (pytest.ini/conftest protected, apply to every parallel implementation, `git status --short`
  before submit). Both rebuilt byte-exact with provenance: `submission_build/flexonafft_v2_20261015/`
  (zip sha 53714f0e…) and `submission_build/honghanhhh_v3_20261015/` (zip sha ed31ecf5…).
  `scripts/build_from_notebook.py` now resolves `json.loads(...)` and variable-referenced FILES.
  Both v2/v3 register the three graph tools in `agent.yaml` while the prompt forbids using them.
- **Public sweeps say the sampling knobs are noise** (temperature, top_p, thinking 2048–6144:
  ±0–3 tasks on 129 tasks), while disabling thinking halves the score and dropping thought
  summaries costs a third. Do not spend submissions there. No LoRA result has been published; one
  notebook (sauravbellam) has an RFT data pipeline and no training.

## Failure anatomy of the 380 runs (`results/eval_matrix_20261014/out/`)

- The 95 tasks are bimodal: 26 solved in all 4 arms, 47 in none, 22 flip. Pass@4 = 48/95 against
  pass@1 37–39.
- Resolve rate by gold-patch size (A arm): ≤5 lines 21/32, 6–15 11/22, 16–40 3/18, 41–100 2/11,
  >100 0/12. 17 of the 47 never-solved tasks have >50-line gold patches — out of reach for any
  scaffold.
- A arm's 58 failures: right file, wrong fix 16 (4 exact-string contracts absent from the issue,
  5 missed a second change in the same file, 6 wrong root cause, 1 harmful extra edit); partial
  files 9; wrong files 11; patch breaks imports 9 (all large new-feature tasks); empty 13. In every
  failure only the task's new tests fail — zero regressions.
- **Tool-call reliability is the largest cheap loss.** `edit_file` succeeded on 657/1154 calls
  (57%); 361 (31%) arrived malformed because the tool-call serialization shreds `old_string` on
  `:` (harness reply: "mandatory input parameters are not present: old_string"). By arm: A 62%,
  B 50%, C think2k 48%, D edit-recover 71% — less thinking worsens formatting; D's single fallback
  line halves malformed calls. `write_file` succeeded on 15/201 (7%): 155 were `/tmp/...` paths
  the tool rejects as path traversal, each burning a call.
- **Empties (56 across arms; 21 on tasks another arm solved):** 27 attempted their first edit only
  after the 28-call cap (13–19 read_file + 10–18 run_command first), 16 never attempted an edit,
  4 looped one malformed edit until the wall clock, 4 lost the last calls to old_string misses,
  4 to rejected /tmp writes. The "edit by call 12" rule is not followed.
- Latency is model generation, not tools: edit_file 12 s, write_file 19 s, run_command 5.3 s,
  read_file 2.9 s per call. Resolved runs land the first edit at call ~10 / 121 s; unresolved at
  call 15 / 211 s. Only 17 pytest invocations in 95 A runs; local checks were mostly ad-hoc scripts
  that exited 0 without exercising the hidden test's case.

## Plan to 0.30 — tests in order

The exchange rate is the unknown: A_recipe is 37/95 locally and 9/58 publicly. Until T0
calibrates it, assume public ≈ 0.4–0.55 × local, so 18/58 needs roughly 55–60/95 locally — near
the ceiling the gold-size table implies. The levers below must stack; the realistic landing zone
is 0.24–0.31.

**T0 — Re-anchor on the field's validated recipe.** (a) Submit `flexonafft_v2_20261015`
byte-exact after a pinned-SDK compile check. Expect 12–13/58. ≥12: the pipeline is fine and the
v2 config is the new base. ≤10: something systematic in our submission path — stop and investigate
before anything else. (b) Local paired screen A_recipe vs v2 vs v3, 95 tasks, 1 sample each
(≈9 GPU-h, ≈$45): two local↔public points for the exchange rate, and picks v2 vs v3 as the base
prompt. (c) Day 2: submit v3 if its local result ≥ v2.

**T1 — Tool-call reliability arm** (prompt + tool list; 2 samples ≈ 6 GPU-h). On the base: remove
`write_file` from `tools`; edit protocol = `edit_file` with a ≤3-line colon-free `old_string` when
possible, otherwise a `run_command` Python heredoc with an exact-once assertion as the primary
path; scratch files only via `run_command` into /tmp; first edit by call 8; one `get_status` after
call 6. Expected: malformed edits 31% → <10%, empties −4 to −6/95, resolved +3 to +5/95. Promote at
paired W−L ≥ +4 over 2 samples with sign-test p < 0.1.

**T2 — Reviewer stage** (`SequentialAgent` [solver → reviewer]; 2 samples ≈ 6 GPU-h). The
reviewer (read_file, run_command, edit_file, submit_patch; sees history) runs `git status --short
&& git diff`, re-derives the issue contract, checks for a missed parallel/second change and stray
files, makes ≤1 corrective edit, guarantees a non-empty diff, submits. Targets the 5 incomplete,
1 harmful-extra, 5 stray-file and the stopped-without-edit cases: +2 to +4/95. Risk: starved when
the solver spends all 28 calls (35/56 empties ended at the cap) — run only on top of T1.

**T3 — LoRA rejection-sampling SFT** (the lever the field has not used; 3–5 weeks, ≈$300–450).
(a) Harvest with the post-T1 base at temperature 0.7, 6 samples × 103 sound tasks (95 + 7 requests
+ 1 httpx) ≈ 620 runs ≈ 20 GPU-h; capture exact request/response payloads at the proxy (reuse the
2026-10-13 transport capture); keep resolved, ≤3 per task, fewest calls first, ≤16K tokens,
well-formed calls only → expect 150–200 trajectories. (b) Train: Fireworks managed SFT on
`gemma-4-31b-it` (listed tunable; LoRA rank ≤32; OpenAI chat JSONL with tools, tool_calls and
reasoning_content; $3/M training tokens ≈ $25 per run); `firectl model download` → PEFT
safetensors (harness: rank ≤128, <3 GiB). Fallback on base-mismatch symptoms: self-hosted PEFT on
`google/gemma-4-31B-it-qat-q4_0-unquantized` (the bf16 QAT twin), 2×A100-80GB. (c) Gates: G1 the
adapter loads under vLLM `--lora-modules` on the w4a16 model, 12 tasks, tool-call format intact;
G2 paired 95-task, 2 samples, ≥ +5 over base; G3 held-out split (train on 60% of tasks, test on
40% + requests/httpx) ≥ +3/38. Submit only past G3. Expected +5–10/95 local (format reliability,
early edits), +2–4/58 public. If G2 passes, grow the data 5–10× with SWE-smith-style synthetic
tasks on the four public repos.

**T4 — Submission discipline.** One per day, SD ≈ 2 tasks: submit only anchors (T0) and candidates
with 2-sample paired evidence ≥ +4. Keep 8 min / 28 calls / 240 s (12-hour cap; `timeout_seconds`
may still bound the grading pytest on the scorer). Final two picks: safest + most different (public
order carries to private only ~50–80% of the time). Not worth submissions: temperature, top_p,
thinking budget, thinking off, analyzer or graph tools.

Compute ask: ≈45 GPU-h A100 spot (~$225) + Fireworks ~$50–150 over four weeks. The prior $100
authorization covered the previous line of work only.

## Anchor result (ref 57214360 scored 2026-10-15 ~23:00 UTC): 0.12 = 7/58 — and why

The decision rule said ≤10 → investigate. Investigation outcome: **our submission path is fine;
the baseline assumption was wrong.** The flexonafft `budget-aware v2` notebook states in its own
header that *"this candidate has not been scored"* (the author's scored variant got 0.18); the
"public 0.22" label was honghanhhh's unverified attribution, and the 19-team 0.22 cluster is not
evidence for these bytes. Our static FILES→zip reconstruction is exactly what the notebook builds.
Scoring has not changed (10-15 submissions still reach 0.20–0.24, max 0.24 at 01:42 UTC). The top
teams run something other than the public notebooks.

**Exchange rate, now with two points:** A_recipe 36/95 local → 9/58 public; v2 34/95 local →
7/58. Public ≈ 0.35–0.4 × local. The hidden repositories are far harder for this model than
FastAPI/Rich, and no locally measurable prompt change bridges that; even a perfect local score
would map to roughly 0.20. The LoRA (T3) can only reach 0.30 if what it learns transfers across
repositories — tool discipline, early edits, exact-string contracts — rather than FastAPI
knowledge. Treat the held-out FastAPI/Rich gate as necessary, not sufficient; the public score is
the only test of transfer.

**Decision (user, 2026-10-15 23:20 UTC): hold the 2026-10-16 Kaggle slot for the LoRA** — submit it only if G1 passes and the held-out screen shows a clear paired win; T1 is not submitted.

## T3a harvest: COMPLETE (2026-10-15 17:44–20:55 UTC) — training set built; SFT job running

**Result:** 570 runs (T1 protocol, temperature 0.7, 6 samples × 95 tasks), **218 resolved
(38.2%)**, per sample 38/35/38/34/35/38 — stable at the T1 rate, so the harvest is the planned
size. 48/95 tasks solved at least once, 47 never. Successes: 143 on the 57 training tasks (30
distinct), 75 on the 38 held-out tasks (18 distinct). Everything is under
`results/harvest_20261015/` (out/, logs, `sft_train.jsonl`, `sft_eval.jsonl`, task splits).

**Training data (built, uploaded, validated):**
- `sft_train.jsonl` — 113 clean examples from 33 training-split tasks (harvest + both matrices,
  cap 4/task, no malformed/post-budget tool results, ≤16K context; median 38 messages, 17 tool
  calls, 14.4K tokens). Mixed system prompts (T1 family 63, V2 19, A-family 28, V3 3) — kept for
  volume; all passed the clean-tool-call filter. Fireworks dataset `swe-rft-h1` (READY, 1.66M tok).
- `sft_eval.jsonl` — 38 examples from 19 held-out tasks, for loss monitoring only. Fireworks
  dataset `swe-rft-h1-eval` (READY, 609K tok). Held-out leakage into train: 0 (checked).

**SFT job bem0ovcd FAILED at 23:23 UTC** after 52 min with "Internal error occurred, please contact the Fireworks AI team": no metrics were written and no output model exists, so it never reached training. Suspects: platform/initialization problem, or the Gemma 4 trainer rejecting the tool-calling + `reasoning_content` format at template-render time (upload validation passed). Fallback datasets with the reasoning folded into `content` are built: `results/harvest_20261015/sft_train_content.jsonl` / `sft_eval_content.jsonl`. Retry (user must run; mutating): new output name, lower memory (`--max-context-length 16384 --batch-size-samples 2`).

## 2026-10-20 14:05 UTC: KAGGLE REF 57412209 (v3 ADAPTER) FAILED — "exceeded the allowed runtime"

Status COMPLETE, no score; `error_description` (via the Kaggle Python API — the CLI table does not show it): *"Your submission notebook exceeded the allowed runtime. Review the competition's Code Requirements page for the time limits."* The sample `eval_config.yaml` states the constraint: **global ceiling 12 hours across all ~120 hidden tasks, run sequentially; container setup excluded (agent-loop time only)** → the agent loop must average ≲ 6 min per task. T1 (no adapter, mean 392–435 s per task locally) passed at 0.17; the v3 adapter (mean 409 s locally, plus vLLM LoRA overhead on 4× L4 and `max_time_minutes: 8` worst case 16 h) did not. **Consequences:** (1) any adapter submission must carry a tighter budget — `max_time_minutes: 6` (worst case 12 h) or 5.5 for margin — and/or be faster than T1 per task; (2) T1 itself is near the edge, so a T1 @ 6–7 min variant is the safer baseline for final selection; (3) harvest 2 suggests a 6-min budget costs little (39% success at temp 0.7 on training tasks). **Next local test (after the v4 verdict): paired 38 × 3 of T1 @ 8 min vs T1 @ 6 min vs v4 @ 6 min** (`max_time_minutes: 6` in the arm's `eval_config.yaml`), ≈ 1.5 h; the candidate for upload is whichever 6-min arm is ≥ T1 @ 8 min. The v3 run's local runtime profile is the right proxy: mean task seconds in `gates_analysis*.json`.

## NEXT LINE (evidence 2026-10-20 14:20 UTC): T2 "VERIFY BEFORE SUBMIT" PROMPT VARIANT

Trace analysis of T1's 228 held-out runs (`out_gates_v3` + `out_gates_v4`, `T1_toolfix`): runs that **re-ran the reproduction or tests after their last edit resolved 51% (26/51) vs 24% (42/177)**; runs that ran `pytest` at all 47% vs 26%; merely reproducing at some point made no difference (31% vs 29%); only 22% of runs verify today. Resolved runs take median 315 s / p75 432 s / p90 477 s and 23 tool calls. Part of the gap is selection (verifying runs made an edit and had time), but verification is the cheapest lever left (1–2 calls, 30–60 s) and attacks the wrong-patch bucket (25% of runs). **Design for T2:** (1) first calls: turn the issue's snippet into a `python -c` reproduction or find the failing test — no repo tour; (2) grep the stack-trace / issue symbols, edit; (3) *mandatory* before finishing: re-run the reproduction and the nearest test file (`pytest tests/<file> -x -q`, seconds), one fix round if it fails, submit when it passes or the clock is low. Prompt-only (optionally a small `run_tests` helper that picks the test file matching the edited module), no training, no scorer-runtime penalty; evaluate as `T2_verify` vs `T1_toolfix` on the 38 × 3 paired protocol under the 6-min budget once the budget test has reported.

## LoRA v4 GATED 2026-10-20 ≈ 09:30 UTC — NEUTRAL (net −1); LoRA SFT LINE CLOSED; 6-MIN BUDGET TEST RUNNING

**v4 32/114 vs T1 33/114 (incl. G1 39/126); W 5 / L 6, net −1, p = 1.0.** Longer runs (417 s vs 398 s), fewer wrong patches (16 vs 26) but more timeouts (62 vs 36). Three adapters (v2 excluded) are neutral at best and adapters cost scorer runtime (ref 57412209 timed out) → **no more SFT iterations on this data**; the adapters stay as artifacts (`results/harvest2_20261019/adapter_h4_*`, `submission_build/lora_h4_20261020/` not uploaded). Report: `results/harvest_20261015/GATES.md` (v4 section); raw outputs `results/harvest2_20261019/gates_v4/`.

**Running (launched 14:05 UTC): `~/matrix/run_6m.sh`** — arms `T1_6m` and `G1_lora_6m` (copies of `T1_toolfix` / the v4 `G1_lora` arm with `max_time_minutes: 6`) on the 38 held-out tasks × 3 into `out_gates_v4`, paired by `analyze.py` against the T1 @ 8 min runs already there → `gates_analysis_6m.json`, marker `GATES_6M_DONE` (≈ 15:30 UTC). Decision rule: if T1_6m ≈ T1 @ 8 (net ≥ −3), the scorer-safe 6-min budget becomes the default for every submission (a T1 @ 6 zip is then the safest baseline for final selection); if v4 @ 6 beats T1 @ 8 by net ≥ +9 (p < 0.1) it is a candidate again (with the 6-min budget); otherwise tear down the VM (delete VM + disk, keep snapshots) and move to T1 prompt/tool work (reviewer stage) under the 6-min envelope. Spot watchdog armed (restarts servers with the v4 LoRA module and reruns `run_6m.sh`). **Scorer-safe baseline candidate built, NOT uploaded:** `submission_build/t1_6m_20261020/submission.zip` (T1 tree with `max_time_minutes: 6`, tree at `submission_build/_trees/t1_6m/`, zip sha `9407a15f…`, 4.6 KB; the zip is gitignored — rebuild with `cd submission_build/_trees/t1_6m && COPYFILE_DISABLE=1 zip -r -X ../../t1_6m_20261020/submission.zip .`).

### v4 training record

Held-out eval loss 1.105 → 0.321 (epoch 0) → **0.256** (epoch 1) — within noise of v3 (0.325 → 0.249) despite the different data; train loss 1.04 → 0.22; no preemption; peaks ≤ 34.5 GiB. Adapter `~/train/adapter_h4` (+ `epoch0/`, `epoch1/`), fp32 copy → `results/harvest2_20261019/adapter_h4_final/`. The gate waiter launches `GATES_OUT=~/matrix/out_gates_v4 run_gates.sh ~/train/adapter_h4` on the save (G1 12 tasks, then 38 × 3 paired vs T1) → verdict ≈ 09:45 UTC; same bar. Note: the token-level loss is now clearly saturated across v3/v4 at ≈ 0.25 and tells us nothing about task gains — only the gate does. **Candidate built, NOT uploaded: `submission_build/lora_h4_20261020/submission.zip`** (T1 tree + bf16 `adapter_h4_packaged` as `swe_rft_h1`, sha `eccf2bc1…`, adapter sha `c98fefb2…` = the bytes served in the gate; pinned-SDK compile ok on the VM) — upload only if the gate passes and the user agrees.

### Harvest 2 and the v4 data (03:10 UTC)

**Harvest 2 (23:54–03:07 UTC): 684 runs, 267 resolved (39%), but only 33 of the 57 training tasks were ever solved under the 6-minute budget** (24 hard tasks contribute nothing). Copied to `results/harvest2_20261019/out_harvest2/` (104 MB). **v4 training set `results/harvest2_20261019/sft_train_v4.jsonl`: 121 examples from 28 tasks** — resolved runs from both harvests on training tasks, ≤ 24 tool calls, fewest-call successes first, 5 per task (median 16 calls, p90 22; v3's data: median 17, p90 27). Alternatives measured: 4/task ≤ 20 calls → 85 ex / 25 tasks; 6/task ≤ 28 → 153 / 30; the task-coverage ceiling is ~30 whatever the cap. Filter reasons over 1254 runs: not_resolved 616, held-out tasks 228, >24 calls 78, malformed/post-budget tool result 67, >16K prompt 14, over cap 130, kept 121. **v4 = v3 recipe on this set**: `--train sft_train_v4.jsonl --out ~/train/adapter_h4 --max-thinking-chars 600 --lr 5e-5 --epochs 2` + memory flags (same eval set `sft_eval.jsonl`). Launched 03:10 UTC after the vLLM replicas were stopped; watchdog (resume from `adapter_h4/epoch*`), progress monitor and gate waiter (`GATES_OUT=~/matrix/out_gates_v4 run_gates.sh ~/train/adapter_h4`) armed. ETA: adapter ≈ 06:30 UTC, gate verdict ≈ 08:30 UTC. Gotcha fixed in `post_harvest2.sh`: `pkill -f "vllm.entrypoints"` inside an ssh command kills the ssh shell itself (exit 255) — use the `[v]llm` bracket pattern.

## 2026-10-19 23:18 UTC: v3 UPLOADED AS KAGGLE REF 57412209 (user: "go for it, submit and see"); HARVEST 2 QUEUED (user: "let's get started on the larger subset")

`submission_build/lora_h3_20261019/submission.zip` (sha `488652b4…`) submitted at 23:18:22 UTC, PENDING; expected ≈ T1's 10/58 ± 2 — its purpose is to prove a real adapter (490 MB bf16 LoRA, `adapter: swe_rft_h1`, `openai/swe_rft_h1`) runs through the scorer. **Read its score and status next session** (a scorer error = the LoRA line needs a packaging fix before anything else). **Harvest 2** (plan step 2): `~/matrix/run_harvest2.sh` on the VM — `T1_harvest` arm (T1 prompt, temp 0.7, base model), `train_tasks.txt` (57 training tasks) × 12 samples (`--first-sample 0 --seed 1`, distinct from harvest 1's seed 0), **6-minute budget via `--time-scale 0.75`** so only efficient trajectories survive, 4 endpoints × 5 workers → `~/matrix/out_harvest2/` (≈ 684 runs, ≈ 3.5 h, marker `HARVEST2_DONE` in `~/matrix/harvest2.log`). **Launched 23:54:40 UTC 2026-10-19** (after `GATES_O4K_DONE`); a local Spot watchdog restarts the servers (`serve.sh`, base model) and re-runs `run_harvest2.sh` on preemption (the matrix runner resumes via per-task claims). **Capped-v3 result (`G1_lora_o4k`, 23:54 UTC): 30/114 vs T1 35/114, W 4 / L 9, net −5, p = 0.27** — no change in verdict; v3 ≈ T1 − 4 with or without the cap (`gates_analysis_o4k.json`). Then **`scripts/rft/post_harvest2.sh`** (one command): copies `out_harvest2` to `results/harvest2_20261019/`, builds `sft_train_v4.jsonl` from both harvests' resolved runs on the 57 training tasks (the builder already sorts by tool calls and keeps the first `PER_TASK`=4 per task; `MAX_CALLS`=20, `MAX_PROMPT`=16384), prints the counts, and with `LAUNCH=1` uploads the set, stops the vLLM replicas and starts v4 training (`--out ~/train/adapter_h4`, v3 recipe: `--max-thinking-chars 600 --lr 5e-5 --epochs 2` + memory flags). Then gate 38 × 3 vs T1 as before (`GATES_OUT=~/matrix/out_gates_v4 run_gates.sh ~/train/adapter_h4`).

## LoRA v3: GATED 2026-10-19 23:09 UTC — NEUTRAL (net −4, p = 0.52)

**Screen: v3 31/114 (27.2%) vs T1 35/114 (30.7%); W 9 / L 13, net −4, p = 0.52** — the "roughly equal" zone of the pre-registered rule. First adapter that does not degrade the agent: terser (109 vs 124 tokens/call), faster steps (4.9 vs 5.5 s), loops down to 0.5% of calls (13 of 2776; v2 2.7%) — but those 13 loops still explain the extra timeouts (53 vs 38). Full report: `results/harvest_20261015/GATES.md` (v3 section); raw outputs `results/harvest_20261015/gates_v3/`. **Follow-up running: `G1_lora_o4k`** (same adapter, `max_output_tokens: 4096`) launched 23:12 UTC on the same 38 × 3 into `out_gates_v3` (≈ 1 h → `GATES_O4K_DONE`, `gates_analysis_o4k.json`). **Candidate zip built and verified, NOT uploaded:** `submission_build/lora_h3_20261019/submission.zip` (382 MB, sha `488652b4…`, pinned-SDK compile ok); recommended to the user as a scorer-path validation upload for the 10-19 slot (closes 24:00 UTC) — awaiting their word. Next per plan: if the capped arm is ≥ neutral, proceed to the large harvest for v4; stop the VM meanwhile.

**Training done 21:32 UTC** (one Spot preemption 19:19 UTC, auto-resumed from `epoch0`): held-out eval loss 1.105 → 0.325 (epoch 0) → **0.249** (epoch 1); train loss 1.20 → 0.18; peaks ≤ 35.3 GiB. Adapter `~/train/adapter_h3` (+ `epoch0/`, `epoch1/`), copies → `results/harvest_20261015/adapter_h3_final/` (fp32) and `adapter_h3_packaged/` (bf16 as served). **Gate auto-launched 21:32 UTC → `~/matrix/out_gates_v3`.** G1 smoke: **7/12** (v1 8, v2 3), 4 timeouts, 1 empty. **The loops are gone:** per-call completion median 104–119 tokens (T1 121), p90 ≈ 580 (T1 746), only 5 of 1743 calls at the 8192 cap (0.3%; v2 2.7%), 5 nudges. Screen at 22:33 UTC (69 of 114 runs each): v3 18 resolved vs T1 19 — tracking *neutral*; wall median 487 s vs 435 s (v3 still a bit slower per run). Verdict ≈ 23:15 UTC; bar: net ≥ +9 & p < 0.1 → submit (ask user); roughly equal → user decides (plan says: proceed to the larger harvest for v4); net ≤ −9 → stop the LoRA line.

Exact launch (VM `~/train`): `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True nohup .venv/bin/python -u train_lora.py --model /home/davidproctor/hf/gemma4-bf16 --train sft_train.jsonl --eval sft_eval.jsonl --out /home/davidproctor/train/adapter_h3 --max-len 20480 --epochs 2 --rank 32 --lr 5e-5 --grad-accum 8 --layer-split 15,16,16,13 --head-chunk 512 --offload-ckpt --mem-probe --probe-max-gib 38 --max-thinking-chars 600 > train.log 2>&1 &` (trainer md5 13438179…, same as the repo). Local automation: Spot watchdog (resumes from `adapter_h3/epoch1 --start-epoch 2` or `epoch0 --start-epoch 1`), progress monitor, and a waiter that launches `GATES_OUT=~/matrix/out_gates_v3 run_gates.sh ~/train/adapter_h3` when `saved adapter` appears. ETA: adapter ≈ 20:30–21:00 UTC, gate verdict ≈ 22:30–23:00 UTC (10-19 Kaggle slot closes 24:00 UTC). v2's final log kept as `~/train/train_v2_final.log`.

### Decision record (03:10 UTC; user: "whatever makes the most sense; the goal is to win")

**Plan (staged):** (1) train v3 on the existing data — `--max-thinking-chars 600 --lr 5e-5 --epochs 2 --rank 32 --grad-accum 8 --max-len 20480 --layer-split 15,16,16,13 --head-chunk 512 --offload-ckpt --mem-probe --probe-max-gib 38`, output `~/train/adapter_h3` (109 examples, 14 steps/epoch, thinking supervised but bounded, half the learning rate) → same gate (`GATES_OUT=~/matrix/out_gates_v3 run_gates.sh ~/train/adapter_h3`), ≈ $35, ≈ 7 h. (2) If v3 is ≥ neutral vs T1 (net ≥ 0): harvest at scale — 12 samples/task on the 57 training tasks with a 6-min budget, keep the fastest successes (≈ 20 GPU-h, ≈ $100) — and train v4 on that. (3) If v3 is clearly worse (net ≤ −9): stop the LoRA line, delete VM + disk, and run the T2 reviewer stage on T1 (T1's dominant failure is wrong patches, 30/114). Rationale: public leaders cluster at 0.22–0.24 with prompt-only recipes and our four prompt arms plateaued at 36–40% locally; the adapter is the lever the field has not landed, and v1/v2 failed for identified, fixable reasons (behavioral shift too large). Restart the stopped VM first (`gcloud compute instances start gemma-train2-20261016 --zone us-central1-f`; the disk already holds the v3 trainer, data, weights and eval env); if Spot stocks out, recreate from `gemma-train-20261015-envsnap` and scp `scripts/rft/train_lora.py`.

## LoRA v2: DONE — NOT PROMOTED (2026-10-17 22:49 UTC)

**Final:** v2 adapter 19/114 vs T1 41/114 (W 1 / L 23, net −22, p ≈ 0); the config-only mitigation `G1_lora_o2k` (same adapter, `max_output_tokens` 2048) 23/114 (W 0 / L 18, net −18, p ≈ 0). Neither is uploaded. Full report: `results/harvest_20261015/GATES.md` (v2 section); raw outputs `results/harvest_20261015/gates_v2/` (job summaries, traces, patches, logs, both analyses, training logs). **VM `gemma-train2-20261016` STOPPED (not deleted) at 22:52 UTC** after all artifacts were copied; its 300 GB disk `gemma-train2-20261016-disk` (us-central1-f) still holds the training venv, bf16 weights, `adapter_h2`, the eval env and `out_gates_v2`. Resume for v3: `gcloud compute instances start gemma-train2-20261016 --zone us-central1-f` (Spot; may stock out → recreate from `gemma-train-20261015-envsnap` and scp the new `train_lora.py`); or delete VM + disk to stop the ≈ $30–50/month disk charge (keep the snapshots). The LoRA line so far: two trained adapters, both worse than the untrained T1 on held-out tasks (v1 verbose/slow, v2 loops); the data (90 trajectories, 57 tasks) and lr 1e-4 × 2 epochs shift the model too far. **Decision for the user:** train v3 (`--max-thinking-chars 600 --lr 5e-5`, ≈ $35, ≈ 7 h incl. gates) or stop the LoRA line and iterate on T1's prompt/tools (T1 = 0.17 public).

### Run log

**Training finished 03:50 UTC (2026-10-17): epoch 1 action-only held-out eval loss 0.088** (0.425 before training → 0.110 after epoch 0 → 0.088); epoch-1 train loss per step 0.04–0.10; per-GPU peaks 32–35 GiB on every step with the balanced layout (no OOM). Final adapter `~/train/adapter_h2/` (also `epoch0/`, `epoch1/`), copied to `results/harvest_20261015/adapter_h2_final/` (weights gitignored). The gate run (`run_gates.sh ~/train/adapter_h2` → `~/matrix/out_gates_v2`, G1 12 tasks then 38 × 3 paired vs `T1_toolfix`) is launched automatically by the local waiter when the save line appears; markers in `~/matrix/gates.log`; verdict ≈ 06:30 UTC against the pre-registered bar (net ≥ +9 & p < 0.1 → submit; roughly equal → user decides; net ≤ −9 → hold).

**T1 SCORED 0.17 PUBLIC = 10/58 (read 2026-10-17 06:05 UTC; ref 57277262) — best so far** (0.15 honghanhhh recipe, 0.12 v2 anchor). T1 is the base now; third local↔public point: T1 36–40% local ↔ 10/58 (≈0.45×). **v2 SCREEN (done ≈ 05:35 UTC): G1_lora 19/114 vs T1_toolfix 41/114 — FAILS the pre-registered bar. Paired: 114 pairs, 1 win / 23 losses, net −22, sign-test p ≈ 0** (`~/matrix/gates_analysis.json`; failure mix G1_lora: timeout 92 of 126 runs incl. G1, empty 7, wrong 4 — T1: wrong 30, timeout 31, empty 12; 450 s vs 408 s per task, 18.8 vs 22.1 tool calls). The gcloud token expired ≈ 05:25 UTC, so the capped-output arm did not auto-launch and the VM sat idle ≈ 16 h; **`G1_lora_o2k` screen launched by hand 22:02 UTC 2026-10-17** (`run_o2k.sh`, ≈ 1 h → `GATES_O2K_DONE`, `gates_analysis_o2k.json`). Lesson: `gcloud auth login` lasts well under a day here — any unattended run longer than ~8 h will lose its monitors; re-login before long waits.

**Candidate built, NOT uploaded (22:10 UTC): `submission_build/lora_h2o2k_20261017/submission.zip`** — T1 prompt tree with `configs/sampling.yaml` `max_output_tokens: 2048` (tree copy at `submission_build/_trees/t1_o2k/`) + the bf16 `adapter_h2_packaged` as `swe_rft_h1`; zip 382 MB, sha256 `dd876455a0caceaa…`, compile check ok (model `openai/swe_rft_h1`, 5 tools). Upload only if `G1_lora_o2k` clears the bar (net ≥ +9 vs T1, p < 0.1) and the user says so; the 10-17 UTC Kaggle slot is unused and closes 24:00 UTC.

**G1 (04:07 UTC): 3/12 for v2 (v1 was 8/12). Diagnosis from the traces: repetition loops.** 8 of 300 LLM calls ran to the 8192-token output cap (5 in the thinking channel, 2 inside a tool call's arguments — e.g. `except Exception as e:` repeated for 31K characters, `Example: ... No.` repeated for 16K); each such call costs 160–275 s, so 7 of 12 runs timed out at 8 min with only 2–19 tool calls, and 9 of 12 ended with an empty patch. Outside the loops the adapter is terse and fast — median 43–56 completion tokens per call vs 133 for the untrained T1 (`--mask-thinking` worked), and the three resolved runs were clean. Mechanism: with thinking masked, nothing in the loss anchors when to stop thinking, and 24 steps at lr 1e-4 on ~115K action tokens (train loss 0.04–0.07) over-sharpened the action distribution; at temperature 0.2 a sharpened model falls into loops. **Mitigation under test (config only, same adapter): `G1_lora_o2k` = `max_output_tokens: 2048`** (T1's legit calls: p99 1136, max 2936 tokens; the LoRA's p99 739) so a loop costs ≤ ~45 s; a local waiter launches `~/matrix/run_o2k.sh` (38 × 3 into the same `out_gates_v2`, pairs with T1 via `analyze.py`, marker `GATES_O2K_DONE`, analysis `gates_analysis_o2k.json`) as soon as `GATES_SCREEN_DONE` appears (≈ 05:30 UTC; ≈ 1 h, ≈ $5 Spot). For a v3 training fix: keep the thinking *boundary* tokens (`<|channel>`, `<channel|>`) and the first ~256 thinking tokens in the loss, lr 5e-5, 1 epoch; or gate the epoch-0 checkpoint (`adapter_h2/epoch0`, less sharpened) first.

**v3 options are implemented and dry-run-verified on the VM (04:50 UTC, no training launched — needs a go-ahead, ≈ 4.5 h training + 2.5 h gates ≈ $35 Spot):** `train_lora.py --max-thinking-chars N` truncates each `reasoning_content` to N characters before rendering (the thinking stays supervised but bounded; the data's thinking is 212 chars median, p90 2286, max 16268) — at N=600 the rendered examples shrink so **109 of 113 fit in 20K tokens (v1/v2: 90)**, median 12.8K tokens, supervised 24%; `--mask-thinking --keep-thinking-markers` masks thinking content but keeps the `<|channel>`/`<channel|>` tokens in the loss (supervised 10%, markers verified in the dry run). Proposed v3: `--max-thinking-chars 600 --lr 5e-5 --epochs 2` (+ the memory flags `--layer-split 15,16,16,13 --head-chunk 512 --offload-ckpt --mem-probe`), output `~/train/adapter_h3`, same gate.

**Epoch 0 (00:07 UTC): action-only held-out eval loss 0.425 → 0.110 (−74%).** Epoch 1 then OOM'd twice: GPU 1 at step 18 (uneven 30-layer shard), and after a resume with `--max-memory-gib 15,15,15,20` (15 layers/GPU) GPU 3 at step 16 (01:32 UTC; it had been pinned at 40 GB from the first step — the activation working set of one 20K-token layer is ~18 GiB, so every GPU runs within a few GiB of the card). **Third launch 01:48 UTC, resuming epoch 1 from `adapter_h2/epoch0`, with the trainer changes below; its memory probe measured peaks of 34.6/32.5/32.3/32.1 GiB on the longest example, so the run should finish: final adapter ≈ 04:30 UTC, then the gates auto-launch (`GATES_OUT=~/matrix/out_gates_v2 run_gates.sh ~/train/adapter_h2`, ≈ 2.5 h → verdict ≈ 07:00 UTC).** Epoch-0 checkpoint copied to `results/harvest_20261015/adapter_h2_epoch0/`. Earlier OOM logs on the VM: `~/train/train_pre.log`, `~/train/train_oom2_*.log`.

`train_lora.py` additions (2026-10-17 01:45 UTC, all memory-only, same math): `--layer-split 15,16,16,13` places decoder layers explicitly (embed/lm_head on GPU 0, final norm + vision tower on the last GPU) instead of accelerate's cap heuristic; lm_head chunks are recomputed in backward (`torch.utils.checkpoint`, `--head-chunk 512`) instead of keeping every 262K-wide fp32 logits chunk alive until backward; `--offload-ckpt` switches to reentrant gradient checkpointing with `torch.autograd.graph.save_on_cpu`, parking each layer's 20K×5376 input in pinned host RAM (~0.2 GiB per layer per GPU); `--mem-probe` runs forward+backward on the longest and most-supervised examples before training and exits 3 (`PROBE_FAIL`) if any GPU peak exceeds `--probe-max-gib` (38); each step record in `train_log.jsonl` now carries `peak_gib` per GPU. Exact launch: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True nohup .venv/bin/python -u train_lora.py --model ~/hf/gemma4-bf16 --train sft_train.jsonl --eval sft_eval.jsonl --out ~/train/adapter_h2 --max-len 20480 --epochs 2 --rank 32 --lr 1e-4 --grad-accum 8 --layer-split 15,16,16,13 --head-chunk 512 --offload-ckpt --mem-probe --probe-max-gib 38 --mask-thinking --resume-adapter adapter_h2/epoch0 --start-epoch 1 > train.log 2>&1 &` (the local Spot watchdog uses the same, preferring `epoch1 --start-epoch 2` if that checkpoint exists). Note: on resume the per-epoch shuffle restarts from the seed, so epoch 1 replays epoch 0's example order — harmless for the objective.

Single change vs v1: `train_lora.py --mask-thinking` — the loss covers only the actions (tool calls, final text); `<|channel>…<channel|>` thinking blocks are excluded (supervised tokens 36% → 10%). Same data (90 train / 28 eval at a 20K cap), r=32 α=64, 2 epochs, lr 1e-4, grad-accum 8, max_memory 22 GiB/GPU. VM `gemma-train2-20261016` (Spot a2-highgpu-4g from `gemma-train-20261015-envsnap`, disk `gemma-train2-20261016-disk`); output `~/train/adapter_h2`; gates via `GATES_OUT=~/matrix/out_gates_v2 bash ~/matrix/run_gates.sh ~/train/adapter_h2` (same 38×3 paired protocol, same bar: net ≥ +9, p < 0.1). Eval loss is now on action tokens only — not comparable to v1's 0.138.

**Kaggle 10-16 slot used (user decision): T1 submitted as ref 57277262 at 17:20 UTC** (`submission_build/t1_toolfix_20261015/submission.zip`, sha c61aae4b…; expected 7–9/58; it is the clean-tool-protocol prompt, locally never worse than v2). Read its score next session; it is the third local↔public calibration point.

**GATE VERDICT (16:10 UTC): NOT PROMOTED.** Held-out screen 38×3 paired: G1_lora 29/114 (25.4%) vs T1 39/114 (34.2%), W5/L15, net −10, p = 0.041 — below the pre-registered hold line. The adapter's tool calls are flawless but it writes ~20% more per step, takes ~20% longer per call, edits less, and ends 55/114 runs with an empty patch at the budget (untrained: 38). Full analysis and v2 plan: `results/harvest_20261015/GATES.md`. The LoRA zip (`submission_build/lora_h1_20261016/`) is NOT to be uploaded. Training/gates VM and disk deleted 16:11 UTC; snapshots kept (`gemma-train-20261015-envsnap` has the venv, bf16 weights, adapter and eval env). The 10-16 Kaggle slot is unused — options: T1 (clean tool protocol, never worse than V2 locally) or hold.

**Pre-registered decision bar for the screen (38 held-out tasks × 3 samples, paired G1_lora vs T1_toolfix):** submit the LoRA if net wins ≥ +9 over the 114 paired runs (≈ +3 tasks per 38-task pass) with sign-test p < 0.1; if it is roughly equal (|net| < 9), it is still the low-regret use of the otherwise idle 10-16 slot given the token-level evidence and clean tool use — user decides; if it is clearly worse (net ≤ −9), do not submit. Submission candidate pre-built: `submission_build/lora_h1_20261016/` (T1 prompt tree + bf16 adapter `swe_rft_h1`).

**G1 PASSED (14:44 UTC): 8/12 held-out smoke tasks resolved (untrained expectation ≈ 8–9), zero malformed tool calls, landed edit in 11/12 runs, median first edit at call 7 (untrained T1: 11–12).** Screen running. `scripts/rft/gates_report.py OUT_GATES --base-counts results/harvest_20261015/base_success_counts.json` prints the G1 table and the paired screen summary.

**Gate run (second launch 14:28 UTC; the first never served and the VM was preempted 06:46):** `GATES_SERVE_OK` at 14:34 — the adapter loads on the w4a16 model under vLLM (G1 load check passed; KV cache 16.2K tokens). Cause of the first failure: the scorer's `--max-loras 8 --max-lora-rank 128` leave 0.57 GiB of KV cache on a TP=1 A100-40GB; `serve.sh` now defaults to 1 slot / rank 32 (`LORA_MAX_LORAS`, `LORA_MAX_RANK`). G1 12-task round, then the 38×3 held-out screen; results in `~/matrix/out_gates/`, `~/matrix/gates_analysis.json`.

**TRAINING COMPLETE 05:40 UTC: held-out eval loss 0.458 → 0.163 (epoch 0) → 0.138 (epoch 1).** Final adapter at `~/train/adapter_h1` on the VM and `results/harvest_20261015/adapter_h1_final/` locally (weights gitignored, config + `train_log.jsonl` committed). `run_gates.sh` auto-launched 05:40:35 UTC — follow `~/matrix/gates.log`.

**Timeline (2026-10-16 UTC):** resumed epoch 1 at step 19/24 by 05:02 (train loss ≈0.10–0.16); final eval + save ≈ 06:00; a local waiter launches `run_gates.sh ~/train/adapter_h1` automatically when `saved adapter` appears (gates ≈ 2 h → decision ≈ 08:00 UTC; the 10-16 Kaggle slot is held for the LoRA).

**Preempted 03:32 UTC at step 16/24; the watchdog restarted the VM and resumed epoch 1 from the epoch-0 checkpoint at 03:34 UTC** (resume works as designed). New ETA for the final adapter ≈ 05:45 UTC.

**Gate run is one command on the VM:** `bash ~/matrix/run_gates.sh ~/train/adapter_h1` (or `.../adapter_h1/epoch0`) — packages the adapter (`scripts/rft/package_adapter.py`: bf16, list targets, competition base alias), builds `~/matrix/arms/G1_lora`, serves four replicas with `LORA_MODULES`, runs G1 on `g1_tasks.txt` (12), then the held-out screen (`heldout_tasks.txt`, 38 × 3, `T1_toolfix` vs `G1_lora`) into `~/matrix/out_gates/`; markers `GATES_SERVE_OK` / `GATES_G1_DONE` / `GATES_SCREEN_DONE` in `~/matrix/gates.log`, analysis in `gates_analysis.json`. Verified locally with the pinned SDK: `discover_adapters` registers `swe_rft_h1` and the compiled agent routes to `openai/swe_rft_h1` — the same tree zipped is the submission.

**Epoch 0 result (02:58 UTC): held-out eval loss 0.163 vs 0.458 before training (−64%)**; train loss 0.15–0.21 per batch. Epoch 1 running, ETA ≈ 05:00 UTC. The epoch-0 adapter is copied to `results/harvest_20261015/adapter_h1_epoch0/` (safetensors gitignored; config kept) and remains on the VM at `~/train/adapter_h1/epoch0/`.

**Relaunched 00:41 UTC after a CUDA OOM on GPU 2** (uneven shards + 24K attention working set): now `--max-len 20480 --max-memory-gib 22` with `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` → 90 train / 28 eval examples (median 15K tokens). The resume watchdog uses these arguments. Earlier OOM log: `~/train/train_oom.log`.

**Baseline eval loss before training: 0.452** (first run, 35 eval examples at 24K) (per supervised token, 35 held-out trajectories; eval pass took ~15 min → each epoch ≈ 2.5 h, finish ≈ 06:00 UTC). If the Spot VM is preempted: start it, then on it `cd ~/train && nohup .venv/bin/python -u train_lora.py … --resume-adapter adapter_h1/epoch0 --start-epoch 1 > train.log 2>&1 &` once `adapter_h1/epoch0/` exists (otherwise relaunch from scratch); a local `spot_watchdog.sh` with that RESUME_CMD was running.

**Training started 2026-10-16 00:13 UTC** (104 train / 35 eval examples at a 24K cap; LoRA r=32 α=64 on `model.language_model` q/k/v/o/gate/up/down = 245M trainable params; 2 epochs, lr 1e-4, grad-accum 8). Two launch bugs fixed on the way: PEFT cannot wrap the vision tower's `Gemma4ClippableLinear` (target the language-model path only), and `pkill -f` with the script name killed the launching shell itself.

**Self-hosted training VM: `gemma-train-20261015`, zone `us-central1-f`** (Spot a2-highgpu-4g from `gemma-harvest-20261015-envsnap`; disk `gemma-train-20261015-disk`, auto-delete off). Training venv `~/train/.venv` (torch, transformers, peft, accelerate), weights at `~/hf/gemma4-bf16`, trainer and data in `~/train/`. Launch: `cd ~/train && nohup .venv/bin/python train_lora.py --model ~/hf/gemma4-bf16 --train sft_train.jsonl --eval sft_eval.jsonl --out ~/train/adapter_h1 --max-len 24576 > train.log 2>&1 &`. Output adapter `~/train/adapter_h1/` (PEFT; per-epoch checkpoints in `epoch0/`, `epoch1/`; `train_log.jsonl`). Weights were fetched with `HF_HUB_ENABLE_HF_TRANSFER=1 ~/train/.venv/bin/hf download google/gemma-4-31B-it-qat-q4_0-unquantized --local-dir ~/hf/gemma4-bf16` (~1 GB/s on GCP; a quoted `python -c` one-liner silently failed — check the log for a real success line, not the echoed command). The same VM carries the eval environment (`~/matrix`, arms `T1_toolfix` and `T1_harvest`, `g1_tasks.txt`, `heldout_tasks.txt`, `make_lora_arm.py`), so G1/G2 run there after training: stop the trainer, `python3 -I ~/matrix/make_lora_arm.py ~/matrix/arms/T1_toolfix ~/train/adapter_h1 ~/matrix/arms/G1_lora`, `LORA_MODULES='swe_rft_h1=/home/davidproctor/matrix/arms/G1_lora/adapters/swe_rft_h1' bash ~/matrix/serve.sh`, then `TASK_FILE=~/matrix/g1_tasks.txt bash ~/matrix/run_round.sh 0 G1_lora` and the 38-task screen with both arms. Tear down VM + disk after collecting the adapter and results; keep envsnap.

**Fourth attempt `swe-rft-h1d` (qyo10ztq) FAILED (23:47 UTC, ~1 min, same "Internal error")** even though the data renders 113/113 through the HF Gemma 4 template locally. Decision: **self-hosted LoRA** on `google/gemma-4-31B-it-qat-q4_0-unquantized` (bf16 QAT twin, ungated) on a 4× A100-40GB Spot VM created from `gemma-harvest-20261015-envsnap`; trainer `scripts/rft/train_lora.py` (transformers + PEFT, assistant-only loss, rank 32). Fireworks datasets `swe-rft-h1*` remain on the account; a plain-chat probe file exists for their support.

**Fourth attempt: `swe-rft-h1d` (qyo10ztq), created by the user 2026-10-15 23:45 UTC** on the fixed datasets `swe-rft-h1d` / `swe-rft-h1d-eval` (validator accepted object-form arguments); output `accounts/trilogy/models/swe-rft-h1d-lora`.

**ROOT CAUSE FOUND (23:45 UTC):** Fireworks renders Gemma 4 data with the HF chat template, which requires `tool_calls[].function.arguments` to be a JSON *object*; our OpenAI-style JSON *strings* passed upload validation but threw `TemplateError` on every example at render time — surfaced only as "Internal error". `scripts/rft/build_sft_jsonl.py` now emits dict arguments; regenerated `sft_train.jsonl` (113) and `sft_eval.jsonl` (38) render 113/113 and 38/38 through the template locally (`/tmp/render_venv`, transformers CPU-only). Fourth attempt (user runs): upload as `swe-rft-h1d` / `swe-rft-h1d-eval`, create `swe-rft-h1d-lora` (same flags). If Fireworks' validator rejects dict arguments, go self-hosted — our rendering is verified.

**Third attempt `swe-rft-h1c` (pyqy7epw) FAILED too** — ~1 min, same "Internal error", on data without `reasoning_content`, so that field is not the cause. Three strikes on `gemma-4-31b-it` managed SFT. Diagnosis in progress: render every example through the HF Gemma 4 chat template locally (Fireworks' renderer is `google/gemma-4-31B-it`); a plain-chat probe dataset (`results/harvest_20261015/probe_plainchat.jsonl`, 6 short examples, no tools) is ready to test whether Gemma 4 SFT works on the platform at all. Fallback: self-hosted LoRA on the ungated bf16 QAT twin.

**Third attempt: `swe-rft-h1c` (pyqy7epw), created by the user 2026-10-15 23:40 UTC** on the content-variant datasets `swe-rft-h1c` / `swe-rft-h1c-eval` (reasoning folded into assistant content), output `accounts/trilogy/models/swe-rft-h1c-lora`, batch 4, otherwise identical.

**Retry `swe-rft-h1b` (d5zex1qh) also FAILED** — 60 s after creation, same "Internal error", no metrics object (died in dataset processing, never trained). Next attempt uses the `content`-variant datasets (reasoning folded into assistant content, no `reasoning_content`): user uploads `sft_train_content.jsonl` → `swe-rft-h1c`, `sft_eval_content.jsonl` → `swe-rft-h1c-eval`, then creates `swe-rft-h1c-lora` (same flags, batch 4). If that fails too, Fireworks' Gemma 4 trainer is the problem: contact support and/or fall back to self-hosted QLoRA on `google/gemma-4-31B-it-qat-q4_0-unquantized` using the envsnap VM — the weights are **not gated** (62.6 GB, 11 files) and their `chat_template.jinja` (saved in `results/harvest_20261015/`) natively renders tools, tool_calls, tool messages and `reasoning_content`, so transformers+TRL can train on `sft_train.jsonl` directly.

**Retry `swe-rft-h1b` (d5zex1qh), created by the user 2026-10-15 23:32 UTC** — output `accounts/trilogy/models/swe-rft-h1b-lora`, `--batch-size-samples 4`, otherwise identical. G1 task list: `results/harvest_20261015/g1_tasks.txt` (8 held-out tasks the base solves ≥5/6, 4 it solves 1–3/6).

**Original job (created by the user at 2026-10-15 22:31 UTC after `sudo firectl upgrade`):**
`accounts/trilogy/supervisedFineTuningJobs/bem0ovcd` → output model
`accounts/trilogy/models/swe-rft-h1-lora` (rank 32, 2 epochs, 32K context, eval set attached).
Poll with `firectl sftj get bem0ovcd` (read-only works from an agent). When COMPLETED:
`firectl model download accounts/trilogy/models/swe-rft-h1-lora <dir>`, then
`python3 -I scripts/rft/make_lora_arm.py submission_build/t1_toolfix_20261015/source <dir>
submission_build/g1_lora_h1/source` and serve with `LORA_MODULES='swe_rft_h1=<arm>/adapters/swe_rft_h1'
bash serve.sh` (hook added to `scripts/eval_matrix/serve.sh`). G2/G3: `run_matrix.py --task-file
results/harvest_20261015/heldout_tasks.txt --arms T1_toolfix=… G1_lora=… --samples 3`.

**Why the job had to be created by a human:** Fireworks' current `firectl` (1.8.x)
refuses mutating commands when run inside an AI agent for account `trilogy`; the Homebrew
`firectl` 1.7.22 is too old (sends a deprecated `gradient_accumulation_steps` default that
managed training rejects). Run in a normal terminal (after `sudo firectl upgrade`, or with a
fresh binary from `https://storage.googleapis.com/fireworks-public/firectl/stable/darwin-arm64.gz`):
```
firectl sftj create --base-model accounts/fireworks/models/gemma-4-31b-it --dataset swe-rft-h1 \
  --evaluation-dataset swe-rft-h1-eval --output-model swe-rft-h1-lora --display-name swe-rft-h1 \
  --epochs 2 --lora-rank 32 --max-context-length 32768
```
Then: `firectl sftj get <job>` until COMPLETED (read-only, fine from an agent); `firectl model
download accounts/trilogy/models/swe-rft-h1-lora <dir>` → PEFT `adapter_config.json` +
`adapter_model.safetensors`; gate **G1**: load under vLLM `--lora-modules` on the w4a16 model
(VM from `gemma-harvest-20261015-envsnap`, no setup needed), run 12 tasks, tool calls well-formed;
**G2/G3**: paired held-out screen (38 tasks × 3 samples, T1 prompt at 0.2, adapter vs none;
promote only on a clear win on *held-out* tasks). Expected training cost ≈ $10 (≈3.3M tokens).

Infra: one preemption during setup (17:31) and one at 20:41 with 19 jobs left (watchdog restarted
the VM; its Monitor expired mid-recovery so the resume was finished by hand). VM and disk deleted
20:58; **`gemma-harvest-20261015-envsnap` (built environment) and `gemma-harvest-20261015-snap` are
kept** — create future VMs with `--create-disk source-snapshot=gemma-harvest-20261015-envsnap`.

User approved T3 ("go for it"). Harvest agent `T1_harvest` = T1 protocol at temperature 0.7
(`submission_build/t1_harvest_20261015/`), **6 samples × 95 tasks = 570 runs**, ≈4 wall-hours
on **Spot VM `gemma-harvest-20261015-spot`, zone `us-central1-a`**, boot disk
`gemma-harvest-20261015-disk` (from snapshot `gemma-harvest-20261015-snap` of the original;
the environment was rebuilt on it with `remote_bootstrap.sh setup`). requests/httpx tasks are
deferred until a second sandbox image exists.

- Launch (after `SETUP_OK` in `~/bootstrap_setup.log`): `bash ~/matrix/remote_bootstrap.sh serve`
  then `SAMPLES=6 bash ~/matrix/run_round.sh 0 T1_harvest`; progress in `~/matrix/out/progress.log`,
  completion marker `MATRIX_DONE_s0` in `~/matrix/matrix_s0.log`.
- Resume after preemption: start the VM, `serve`, then the same `SAMPLES=6 run_round.sh 0
  T1_harvest` (it removes interrupted job dirs first). Locally:
  `DONE_FILE='~/matrix/matrix_s0.log' RESUME_CMD='timeout 1200 bash ~/matrix/remote_bootstrap.sh
  serve >/dev/null 2>&1 && SAMPLES=6 bash ~/matrix/run_round.sh 0 T1_harvest'
  scripts/eval_matrix/spot_watchdog.sh gemma-harvest-20261015-spot us-central1-a`.
- Collect into `results/harvest_20261015/` (out/, logs, matrix_s0.log, serve.log), then build the
  SFT set: `python3 -I scripts/rft/build_sft_jsonl.py results/harvest_20261015/out --out
  results/harvest_20261015/sft.jsonl --per-task 3 --keep-meta` (then hold out 40% of tasks before
  training — bd-dxbi).
- Tear down after collection: delete the VM and `gemma-harvest-20261015-disk`; keep
  `gemma-harvest-20261015-envsnap`. Never touch `gemma-agent-dev`.

T3b is ready to run the moment the harvest is converted: Fireworks account authenticated
(`firectl` 1.7.22), base `accounts/fireworks/models/gemma-4-31b-it` is `Supervised LoRA
Tunable: true`; `scripts/rft/fireworks_sft.sh upload|train|status|download` wraps the job
(rank 32, 32K context, eval set = `results/harvest_20261015/sft_eval_heldout_existing.jsonl`,
built only from held-out tasks). Train on `train_tasks.txt` tasks only
(`build_sft_jsonl.py --task-file results/harvest_20261015/train_tasks.txt`); gate G1 = adapter
loads under vLLM `--lora-modules` on the w4a16 model with well-formed tool calls on 12 tasks.

## T0b/T1 matrix: completed 2026-10-15 16:07 UTC (760 runs) — T1 not promoted

User authorized the plan's compute (~45 GPU-h + Fireworks) and the T0a upload (**ref 57214360**,
flexonafft v2 byte-exact, still PENDING at session end — check it first; the decision rule is
≥12/58 → v2 config is the base, ≤10 → investigate our submission path).

| Arm | Samples | Resolved | Per sample | Paired vs V2 |
|---|:---:|---:|:---:|:---:|
| T1_toolfix (V3 + tool-reliability package) | 3 | 112/285 (39.3%) | 36, 40, 36 | 18W/13L, +5, p = 0.47 |
| V2_budgetaware (0.22-cluster recipe) | 3 | 107/285 (37.5%) | 37, 31, 39 | — |
| V3_honghanhhh (V2 + 3 prompt edits) | 1 | 38/95 (40.0%) | 38 | 6W/5L, p = 1.0 |
| A_recipe (our 0.15 = 9/58 bytes) | 1 (+1 on 10-14) | 35/95 (36.8%) | 35 (37) | 5W/7L, p = 0.77 |

- **Local noise is ~3 tasks per 95-task sample** (identical V2 config: 37, 31, 39; 10/95 tasks
  flipped). One-sample screens are uninformative; two were barely enough, three settled T1.
- **T1 fails the pre-registered gate** (net ≥ +4 *and* p < 0.1): +5 but p = 0.47. Its mechanics
  worked as designed — malformed `edit_file` 29% → 6%, zero wasted `write_file`, first edit at
  call 11–12 vs 14–17, timeouts 64 → 51 of 285 — but empties rose 32 → 41 and the wrong-patch
  count is identical (81 vs 81). The failure mass is comprehension, not mechanics.
- **Conclusion: the prompt/tool lever is exhausted at ~38/95 locally.** A, V2, V3 and T1 are
  statistically one band. 18/58 on Kaggle needs ~55–60/95 locally. The remaining lever is T3
  (rejection-sampling SFT). Use **T1's protocol as the harvest agent** — its trajectories are
  clean; `scripts/rft/build_sft_jsonl.py` kept only 49 of 149 resolved 10-14 runs because 92
  contained malformed tool results, a problem T1 removes. T2 (reviewer stage) is deprioritized:
  it targets a bucket worth ≤ +4/95 against a noise floor of ±3.
- 50 of 95 tasks were solved by at least one of the 760 runs; 45 by none (the large-gold-patch
  core).
- Full numbers, mechanism tables and chronology: `results/eval_matrix_20261015/RESULTS.md`;
  all job outputs and traces under `results/eval_matrix_20261015/out/s{0,1,2}/`.

Next session, in order: (1) read the ref 57214360 score and apply the decision rule; (2) decide
tomorrow's slot — recommended low-regret use is T1 (never worse than V2 locally, and it is the
harvest configuration, so its public score calibrates the harvest) — or hold if the anchor
disappoints; (3) build T3a: harvest ~620 runs (T1 protocol, temperature 0.7, 6 samples × 103
sound tasks incl. requests/httpx — needs the second sandbox image), convert with
`build_sft_jsonl.py`, then Fireworks SFT (bd-dl9m, bd-dxbi).

Infrastructure for the next run is scripted end to end: `scripts/eval_matrix/remote_bootstrap.sh`
(setup/serve/matrix/resume), `run_round.sh N ARM...`, `spot_watchdog.sh` (round-aware via
DONE_FILE/DONE_MARK/RESUME_CMD), `mechanism_check.py`. Build bundles with `COPYFILE_DISABLE=1`.

What went wrong on the way (all fixed; recipe in `scripts/eval_matrix/remote_bootstrap.sh`):
Spot in us-central1-c was preempted twice within 17 minutes, each ~3 minutes after the GPUs came
under load; on-demand a2-highgpu-4g was stocked out in all nine zones tried (us-central1-a/b/c/f,
us-east1-b, us-west1-b, us-west4-b, europe-west4-a/b) around 05:40–06:00 UTC; Spot in
us-central1-a was available. Two launch bugs: the bundled `swegemma-0.2.11` wheel was the older
build (sha `63f054a3…`, no `verification_timeout_seconds`) — the correct re-release is
`results/runtime_20261012_wheel/` (sha `9ad87658…`); and macOS AppleDouble `._*` files in the
tarball made `adk_submission` reject every job — build bundles with `COPYFILE_DISABLE=1`. Only
`vllm==0.19.1` and `safetensors==0.8.0` in the serving lock are official-wheelhouse builds absent
from PyPI; they are in `results/consumer_verification_20261013/deployment.tar`.

## Cloud, authorization and safety

Authorized this session: ≈45 GPU-h A100 + $50–150 Fireworks for T0b/T1/T2/T3. Spent: about
6 Spot VM-hours of a2-highgpu-4g (≈24 GPU-h, roughly $30–35; two 300 GB disks and two snapshots
for under a day) — settled billing not queried. All matrix resources (VM `gemma-matrix-20261015-spot`,
disks `-disk`/`-disk3`, snapshots `-snap`/`-snap2`) were deleted at 16:12 UTC and prefix-filtered
lists verified empty. Protected original: `gemma-agent-dev` (id 8178724251330271494) TERMINATED
with its 300GB disk (id 7820791868839024902) READY — never delete.

---

# Session handoff — 2026-10-14

## Where we stopped

Goal: beat the 0.12 incumbent and close the gap to the 0.24 leaders.

Two things happened this session. We adopted the **public 0.24 recipe** and submitted it as
**ref 57163806** (PENDING at session end — refresh Kaggle history before claiming anything).
And we built a **scorer-parity local screen** (32K context, starter compaction settings,
per-call latency matched to Kaggle) and ran the recipe plus three single-variable changes over
95 gold-verified tasks. No variant beat the recipe by a detectable margin, so nothing was
promoted and no submission bytes were changed.

Read `AGENTS.md` for the full chronology and `results/eval_matrix_20261014/RESULTS.md` for this
screen's numbers, method and limits.

## Immediate next step

**Check the score of ref 57163806.** It decides the next move:

- At or near 0.18-0.24, the recipe is the new baseline. Build on it; do not restore the old
  90/40/4/100 configuration.
- Near 0.12, the public recipe does not transfer to our account's draws, and the gap to the
  leaders is something other than these settings.

## What was measured, and what it does not say

| Arm | Change from recipe | Resolved /95 | Paired W/L |
|---|---|---:|:---:|
| A_recipe | — | 37 | — |
| B_temp1 | temp 1.0, top_k 64 | 35 | 4/6 |
| C_think2k | thinking 2048 | 38 | 6/5 |
| D_editrecover | shell fallback after 2 rejected edits | 39 | 7/5 |

One sample per arm; about 15% of tasks flip between identical repeated runs, so a ±2 task gap
means nothing. C and D are mildly promising (both cut timeouts) and deserve repeat runs, not a
submission. Temperature 1.0, reported as a gain in two public sweeps, did not reproduce.

The largest failure bucket in every arm is a **non-empty patch that fails the hidden tests**
(28-42 of 95). Budget and sampling tuning cannot move those.

## Next experiments, in order

1. Repeat A/C/D at 2-3 samples before promoting anything (~3 GPU-hours per arm-sample).
2. Analyze the 380 preserved graded runs in `results/eval_matrix_20261014/out/` for why correct-
   looking patches fail. That is where the remaining tasks are.
3. 149 resolved runs are now available as fine-tuning trajectories — the adapters we ship are
   still all-zero, so this is untouched ground with ~7 weeks to the 2026-12-02 deadline.

## Infrastructure now available

`scripts/eval_matrix/` runs a resumable interleaved matrix at scorer parity, one process per
task, with gold/empty controls and a paired sign test. `serving_requirements.lock` rebuilds the
environment; 34 wheels must come from the preserved official wheelhouse rather than PyPI.
Rebuild cost is about 25 minutes of CPU VM time.

## Cloud, authorization and safety

All resources created this session were deleted and verified absent by prefix-filtered listing.
Used 2.59 GPU-hours (~$13) of the authorized $100 / 15 GPU-hours; that authorization is for this
line of work, not a standing allowance. One Spot preemption occurred and was resumed from the
persistent disk.

Protected original: project `ai-coe-454404`, zone `us-west1-a`, VM `gemma-agent-dev`
id 8178724251330271494, TERMINATED; original 300GB disk id 7820791868839024902 READY. Never
delete the original VM/disk. Its boot disk auto-delete flag makes VM deletion dangerous.
Settled billing was not queried.

---

# Session handoff — 2026-10-13

## Where we stopped

Goal: find a measured improvement material enough to warrant another Kaggle submission.
The latest experiment is complete and rejected. No evaluation is running, no new candidate
was uploaded, and the editable submission source was not changed by these experiments.
Best recorded public score is **0.12**. Ref56929785 scored0.08; its exact-byte retry
ref56976207 scored0.12. The same artifact receiving different scores does not isolate a
prompt/configuration cause. Refresh Kaggle history before claiming current submission state.

Read `AGENTS.md` for the detailed chronology, resource rules and evidence limitations.

## What did not earn a submission

|Experiment|Baseline resolved|Candidate resolved|Decision / evidence directory|
|---|---:|---:|---|
|Remove thought history|7/12|2/12|Rejected; `results/history_off_screen_20261011/`|
|Reduce output cap16384→8192|6/12|6/12|One gain and one regression; rejected; `results/repair_transaction_20261012/`|
|Restricted revision-bound editing tools,64K screen|7/12|2/12|One gain and six regressions; rejected; `results/revision_bound_edit_20261013/`|
|Native tools + reproduce-before-edit prompt|8/12|7/12|No gains, one regression; rejected; `results/consumer_verification_20261013/`|

These are separate runs, not a cross-run leaderboard. Each is one sampled paired screen;
the cases are now previously exposed development cases. Earlier32K runs had output-reservation
context failures; the latest native experiment used64K. Local single-A100 results are not
scorer parity or hidden-score predictions. The earlier larger corrected prompt also lost
against its five-case baseline; the narrow source-only prompt preserved3/5, not an improvement.

## What worked — verification and infrastructure, not solving gains

- Real reference/unpatched controls with snapshot import provenance distinguish actual
  source fixes from installed-package false positives. Latest development controls:24 trusted.
- Actual native SDK smoke proved the same consumer probes can observe Rich3471's IndexError
  becoming correct wrapped rendering and FastAPI13920's422 becoming200 with `"value: 123"`.
- Live64K serving and both adapter aliases were verified. A real16-token reasoning clamp
  was observed; the4096 comparison provided a2047-token lower bound, not exact4096 termination.
- Latest14-request raw transport diagnostic preserved exact HTTP bytes, generated token IDs,
  parser replay and actual SDK conversion. SDK preserved all14 API argument objects; eight
  matched requested literals. No parser defect was proven. A malformed quoted native command
  was already malformed in raw model generation. Do not introduce guessed escape repairs.
- Exact dependency closure and grading OCI image are retained; do not reconstruct packages
  from mutable PyPI if these frozen artifacts can be reused.

## Latest failure and evidence

The native reproduce-before-edit prompt increased agent timeouts from4 to8. Candidate had
four normally completed resolutions and three passing patches recovered after timeout;
baseline had eight normal resolutions. Regression `fastapi_9425`: candidate missed the issue's
stringified `"None"` annotation, wrote `repro.py`, timed out and made no implementation fix.
Repeated-command counters do not prove reproduction: captured false positives include a
changed test expectation and repair of an agent-introduced NameError.

Start with these files under `results/consumer_verification_20261013/`:

- `submission_decision.json`: outcome, concrete failure, next hypothesis and limits.
- `model_comparison_64k/comparison_summary.json`: all12 paired outcomes; full arm traces,
  patches, native contracts, JUnit and logs are in the adjacent arm directories.
- `parent_result_validation.json`, `final_evidence_inventory.json`: independent validation.
- `transport_diagnostic/transport_report.json`: all14 observations and attribution limits.
- `experiment_reproduction_sources.zip` + `experiment_reproduction_inventory.json`:
  exact final corrected runners/probes, plans and baseline/candidate ZIPs. Temporary
  top-level Python drivers were removed after byte-identical archival; extract into a fresh
  directory if needed. Initial `deployment.tar` predates the smoke driver's final-LF fix.
- `frozen_dependency_closure/{manifest.json,nonofficial_wheels.tar,sandbox_image.tar}`:
 247 frozen nonofficial wheels and immutable grading image. The41 official wheels remain
  in `deployment.tar`. Image ID is
  `sha256:04716dc0a4b958ebd7b8f5bb313e350d9437088e0c84d17e7e72cb05a6a819e0`.
- `confirmation_cohort.json`, `confirmation_cpu_gate.json`: six prospectively selected
  confirmation IDs, but no model confirmation. `rich_4006` negative control timed out without
  JUnit; do not substitute a case or waive the oracle. Development promotion also failed.

Latest baseline ZIP SHA256:
`75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142`.
Rejected reproduce-before-edit ZIP SHA256:
`e7db4e441ab80d3282f43f9fe76267380457779468d3a091d7e248b52cb750de`.
Do not replace the incumbent with a rejected candidate.

## Next proposed experiment — not implemented or measured

Isolate **thinking_token_budget4096→1024**, retaining the incumbent prompt, native main/analyzer
tools, thought history, output cap16384, sampling and90/40/4/100 budgets. This is not the
already rejected8K output-cap experiment. Both Rich3506 arms generated roughly7.3–7.5K
completion tokens without a source patch; baseline reached only four tool calls before timeout.
Hypothesis: faster reasoning leaves time to implement. Risk: reduced reasoning quality.

Before spending compute: inspect the preserved traces, freeze an exact one-variable artifact,
compile it with the pinned SDK and prove the intended thinking field reaches the provider.
Use the complete paired development screen, not a favorable subset. Previous promotion gate
was net≥2 gains and zero regressions; require clean source-only outputs and trusted prospective
confirmation before recommending upload. Do not present exposed cases as held-out evidence.

## Cloud, authorization and safety

All newly created resources were deleted and prefix-filtered lists verified empty.
Latest GPU start-to-stop6196.375seconds; no restart. `cleanup_receipt.json` and
`gpu_stop_receipt.json` preserve the evidence. No unresolved live compute job remains.

Protected original: project `ai-coe-454404`, zone `us-west1-a`, VM `gemma-agent-dev`
ID8178724251330271494, TERMINATED; original300GB disk ID7820791868839024902 retained.
Never delete the original VM/disk. Its boot disk auto-delete flag makes VM deletion dangerous.
Gcloud authentication succeeded this session, but refresh mutable account/resource state
before acting. The prior $20 /3GPU-hour /2CPU-hour authorization was for the completed run;
it is not a standing authorization for a new experiment or upload. Obtain a fresh compute
allowance before provisioning. Settled billing was not queried.
