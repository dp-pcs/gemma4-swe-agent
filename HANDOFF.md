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

## T3a harvest: IN PROGRESS (started 2026-10-15 ~17:30 UTC) — resume / collect / tear down

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
- Tear down after collection: delete the VM and `gemma-harvest-20261015-disk`; **snapshot the
  built disk first and keep that snapshot** (the matrix snapshot was deleted today and cost a
  second 25-minute build). Never touch `gemma-agent-dev`.

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
