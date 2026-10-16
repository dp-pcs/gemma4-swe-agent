# AGENTS.md — Gemma 4 Developer Agent Competition

Context for agents working on this repository. Distinguish observed results from historical
reports and hypotheses. Recheck mutable external state before acting; do not treat this file
as proof that a build, evaluation, or cloud resource is current.

For a new session, read `HANDOFF.md` first: the2026-10-13 stopping point, measured
experiment index, exact replay artifacts, next unmeasured hypothesis and closed compute
authorization. Detailed evidence and limitations remain below.

## What this is

Kaggle competition **"Google - The Gemma 4 Developer Agent Competition"**
(`gemma-4-developer-agent`, https://www.kaggle.com/competitions/gemma-4-developer-agent).

Goal: build an autonomous SWE agent (powered by Gemma 4) that resolves real GitHub issues
(SWE-bench-style tasks) by producing a patch that passes the issue's hidden tests. Scored on
**resolution rate** = resolved tasks / total tasks.

- Recorded competition deadline: **2026-12-02**; companion paper track
  (`gemma-4-developer-agent-paper`): **2026-11-12**. Recheck the competition pages before planning submissions.
- Beads label used for related work: `gemma4-swe` (global hub, `bd list -l gemma4-swe`).
  Issue statuses have not been refreshed in this review.
- Public task file: **129 tasks** — FastAPI 67, Rich 48, Requests 13, HTTPX 1.
  Approximately 120 hidden tasks is a previously recorded estimate, not a verified current count.
- Recorded submission allowance: **1/day**, resetting at 00:00 UTC. Check history before submitting.

## Submission state: last verified snapshot

Kaggle history was checked on **2026-10-11**:

| Reference | Submitted UTC | Status | Public score |
| --- | --- | --- | --- |
| 56868343 | 2026-10-06 02:48 | COMPLETE | 0.03 |
| 56893727 | 2026-10-07 00:01 | COMPLETE | 0.12 |
| 56929785 | 2026-10-08 02:29 | COMPLETE | 0.08 |
| 56976207 | 2026-10-08 22:38 | COMPLETE | 0.12 |

- The first submission was described as the unmodified starter kit, whose explicit limits
  are 60-second commands, 10 tool calls, 1 agent minute, and 50 turns.
- The preserved local `submission_build/submission.zip` has command timeout **90 seconds**,
  **40** tool calls, **4** agent minutes, and **100** turns. Its system and analyzer prompts
  are byte-identical to the organizer starter prompts. The earlier working prompt edits were
  absent from that local ZIP; do not credit those edits for the score. Kaggle-uploaded bytes
  were not downloaded for independent comparison.
- **Submitted as ref 56929785:** `submission_build/source_only_20261008/submission.zip`
  is byte-identical to `submission_build/next_submission.zip` and matched all ten editable
  source files at build time. It contains the tested narrow candidate. Only `prompts/system.md` differs from the
  preserved reviewed ZIP: explicit source-only grading contract, scratch-tool compatibility,
  and a final changed-file check. Budgets, sampling, analyzer, adapters, and agent YAML are unchanged.
- Ref 56929785 was previously observed in ERROR with API detail: "A system error. Please
  try resubmitting to resolve the error and contact Kaggle Support if it persists."
  The 2026-10-09 API check now reports COMPLETE with public score **0.08**.
- **Exact-byte retry ref 56976207:** `submission_build/source_only_retry_20261008/submission.zip`
  has the same SHA-256 and all file bytes as ref 56929785's preserved artifact. No changes
  were included; the rejected public-API verification candidate was not uploaded.
  Retry provenance is recorded alongside the ZIP in `provenance.json`.
  The 2026-10-11 CLI check reports COMPLETE with public score **0.12**. The same recorded
  artifact scored 0.08 and 0.12; this does not isolate model sampling from scorer/environment
  variation and does not establish that the source-only contract reduced the score.
  Current feedback is preserved in `results/history_off_screen_20261011/submission_feedback.json`.
- The failure-recovery prompt candidate was rejected after a fresh nine-task paired run.
  Editable source has been restored: all ten member names and bytes again match ref 56929785's
  preserved source-only archive. Historical submitted and rejected ZIPs remain unchanged.
- Earlier unsubmitted working prompt drafts are preserved in
  `results/prompt_comparison_20261007/working_before.zip`. The analyzer source was restored to
  the tested packaged version rather than shipping a second unmeasured change.
- Root `agent.yaml` remains the starter configuration. Working and both packaged
  `configs/sampling.yaml` omit the starter's `thinking_level: high`; other sampling fields
  are unchanged.
- Main and tool adapter checkpoints are byte-identical. Direct BF16 tensor inspection found
  nonzero LoRA A matrices and entirely zero B matrices for `q_proj` and `o_proj`, so their
  ordinary LoRA weight updates (`B @ A`) are zero. They provide no learned specialization;
  no fine-tuned adapter or training result is recorded here.

Check current submission status:
```bash
kaggle competitions submissions -c gemma-4-developer-agent
```

**Unproven hypothesis:** tight starter budgets may contribute to the earlier low score.
The higher recorded score does not isolate budget effects from other configuration differences,
and it does not validate edits absent from the reviewed artifact.

## Repo layout

```
competition/
├── AGENTS.md                  # this file
├── kaggle_provided/           # organizer-provided reference (don't edit)
│   ├── HARNESS_README.md      # organizer harness reference; compare with installed version
│   ├── tasks.jsonl            # 129 public tasks
│   └── sample_submission/     # original unmodified starter kit
├── competition_data/           # local working copy, extracted + has our edits
│   ├── sample_submission/     # editable submission source, despite the "sample" name
│   ├── snapshots/, embeddings/, graphs/  # task repo snapshots + code-intelligence data (gitignored, large)
│   └── docker/                # sandbox Dockerfile
├── submission_build/
│   ├── submission.zip         # preserved reviewed artifact, not current editable source
│   ├── next_submission.zip    # tested build, byte-identical to ref 56929785 upload
│   └── source_only_20261008/submission.zip # immutable submitted copy with required filename
├── scripts/
│   ├── verify_ground_truth.py # applies ground-truth patches, runs harness, sanity-checks scoring
│   └── verify_scoped.py       # faster local check: ground-truth patch + scoped pytest, no docker
├── results/                   # local eval run outputs (smoke tests, verify runs)
├── gcp_setup*.sh               # VM bootstrap scripts (model download, venv, docker image build)
└── wheelhouse/                  # pip wheels for swegemma/adk-submission/adk-eval-core/vllm (gitignored)
```

## Packaging and provenance

Edit `competition_data/sample_submission/`; preserve `kaggle_provided/` as the reference.
The source directory and packaged artifact are distinct. Editing source does not update a ZIP
or an already uploaded submission.

- Preserve the artifact associated with each submission before replacing it, including its
  SHA-256, Kaggle reference, effective configuration, and source revision.
- Build a new ZIP from the complete source directory, with `agent.yaml` at the archive root.
  Use a fresh archive rather than updating an existing ZIP or reusing `/tmp/submission_stage`;
  incremental updates can retain obsolete files.
- Compare **all member names and file bytes** against source, not just `eval_config.yaml`.
- Do not describe source-only edits as shipped. Ref 56929785 was accepted from the dated
  source-identical upload copy; the earlier root `submission.zip` is retained as history.
- **Required upload basename: `submission.zip`.** Kaggle rejected `next_submission.zip`
  with HTTP 400 / FAILED_PRECONDITION before creating a submission. Stage verified bytes
  in a new dated directory under the required name; do not overwrite historical artifacts.

The local artifact inspected during review had SHA-256:
`7e5262822e3e773d5cb6363a8d7990be9d621c667fc89b3f74e936d048b6b0b2`.
This identifies the reviewed file, not independently verified Kaggle-uploaded bytes.

Ref 56929785 artifact SHA-256:
`75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142`.
It was built fresh, checked member-by-member against source and tested configuration, and
compiled from the exact extracted ZIP with real harness tools and competition limits.
Accepted on 2026-10-08 at 02:29:47 UTC; previously observed in ERROR with the system-error
message above. The API restored one submission slot after that failure. A later check on
2026-10-09 reports COMPLETE with public score 0.08. Its exact-byte retry, ref 56976207,
was accepted at 22:38:59 UTC and remains PENDING with no score. The CLI reported zero
submissions remaining after that retry; recheck live allowance before uploading.

## Scoring constraints and budget settings

Sources:
- [Kaggle staff clarification](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743063),
  supplied by the user during review.
- [Competition overview](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview).
- `competition_data/HARNESS_README.md` §7.1 documents the submission budget keys and
  setup-excluded agent clock. The two checked-in harness READMEs differ; neither should
  override current scorer instructions or evidence from the installed harness version.

Staff confirmed sequential evaluation and support for exactly four `evaluation:` fields:
`timeout_seconds`, `max_tool_calls`, `max_time_minutes`, and `max_turns`.
The staff reply says omitted scorer limits default to **no limit**. Local CLI defaults and
the starter's explicit limits are separate; do not substitute those for scorer defaults.

- `timeout_seconds` limits each shell command, not the whole task.
- `max_time_minutes` measures the agent loop after sandbox setup.
- The global **12-hour** limit includes sandbox setup but excludes patch validation.
- Staff reported that exceeding the global limit errors the submission and planned to score
  unfinished tasks as zero instead. **The supplied thread does not confirm that fix is live.**
  Treat whole-submission failure as the risk until current evidence says otherwise.

The current 90/40/4/100 settings are experimental, not proven optimal or immutable.
At an estimated 120 tasks, four agent minutes per task permits eight agent hours.
The earlier 1–2 minute/task setup estimate would add 2–4 hours; this is an assumption, not a
measured scoring-run distribution, and its upper bound leaves no margin.

The earlier unsubmitted budget-aware draft would abandon work below 90 seconds; it is no longer
the working prompt. The narrow candidate intentionally retains the starter's other policies for
a controlled change. Its under-8–10-turn goal is not the 40-call hard limit or a measured optimum.
`search_similar_code` is documented as symbol-based lookup; the retained starter keyword-search
instruction remains a caveat, not a validated general natural-language search strategy.

## GCP dev VM

Original instance: `gemma-agent-dev`, project `ai-coe-454404`, zone `us-west1-a`.

Observed during the **2026-10-07** evaluation work:
- The original VM was terminated before an unsuccessful restart attempt. Its 300GB boot disk
  was retained and used to create a temporary evaluation clone; do not delete the original data.
- The original 2x L4 restart and attempted standard 4x L4 provisioning in us-central1-a,
  us-east4-c, and europe-west4-a failed for capacity. These are dated observations, not live
  availability guarantees.
- A temporary **Spot A100 40GB** clone in **us-central1-c** successfully served the existing
  QAT model and adapters. This establishes a working local alternative, not Kaggle hardware parity.
- Working serving parameters: TP=1, **65536-token context**, GPU utilization **0.91**,
  `--language-model-only --skip-mm-profiling --max-num-batched-tokens 2048
  --cudagraph-capture-sizes 1 2`, with the `gemma4` tool and reasoning parsers.
  Exact commands and runtime evidence are retained in `results/prompt_comparison_20261007/`;
  recorded temporary paths must be replaced when reproducing the run.
- Activate `/home/davidproctor/competition/.venv/bin/activate` before launching inference.
  Calling the venv Python by absolute path without activation left the installed `ninja`
  executable off `PATH` and caused model startup to fail.
- Eager inference worked but was substantially slower in the fixed-size probe; benchmark
  request bodies, token counts, and timings are preserved as `inference_benchmark_*.json`.
- A 32768-token server rejected a real task once input plus the configured 16384 output-token
  reservation exceeded that limit. The 65536-token server passed a direct boundary probe
  with 18029 input tokens and the same output reservation; see `context_boundary_smoke.json`.
- The temporary VM's initial two-hour stop limit interrupted an incomplete comparison.
  GCP rejected changing that limit while running; changing it while terminated and restarting
  with a three-hour stop limit succeeded. An interrupted run is not a completed paired benchmark.
- After collecting results, the temporary GPU clone, its boot disk, and the evaluation snapshot
  were deleted. No failed-provisioning instances/disks remained. The original `gemma-agent-dev`
  was confirmed terminated with its 300GB disk retained; only newly created resources were removed.

Historical TP=2 multimodal vision warmup failures with `ncclInvalidUsage` remain unresolved.
Text-only TP=1 success does not prove TP=2 or the scorer's full configuration works.
Earlier Fireworks hosted-inference concerns were not rechecked and do not establish whether
Fireworks is suitable for training.

Inspect the original VM before acting:
```bash
gcloud compute instances describe gemma-agent-dev \
  --zone=us-west1-a --project=ai-coe-454404 \
  --format='yaml(status,machineType,guestAccelerators)'
```
Starting a VM incurs costs; deleting its disk destroys persisted data. Confirm authorization
and data-retention needs before provisioning or deleting.

## Evaluation evidence and limitations

### Source-provenance controls observed on 2026-10-07

- The initial diagnostic Docker image imported Requests from installed `site-packages`,
  not the task snapshot. The provenance guard rejected that run. This confirms a current
  local environment defect; it does not establish the cause of every historical result.
- After giving snapshot source precedence and adding missing `typing-inspection==0.4.4`,
  real Docker `verify_task` controls showed **unpatched failure / reference-patch success**
  for `requests_7315`, `requests_7309`, `requests_7427`, `fastapi_14258`, and `rich_3052`.
  The guard checked imports at pytest startup and after collection; full logs and summaries
  are retained in `results/prompt_comparison_20261007/docker_controls_*/`.
- These are verifier controls, not model-solving rates. The separate host-scoped controls
  also passed the reference cases but are not the full Docker grading result.
- `competition_data/docker/Dockerfile.local` now prioritizes `/workspace/src:/workspace`
  on `PYTHONPATH` and installs the missing dependency. A rebuilt image was exercised with
  actual Requests snapshot imports; see `permanent_sandbox_smoke.json`.
  Existing cached images do not acquire source changes automatically.
- The local snapshot set now contains **15** direct task archives: the original 13 Requests
  archives plus `fastapi_14258` and `rich_3052`. The cloned development disk contained all 129.

On a Linux/amd64 Docker host with the organizer base image already built, rebuild the image
used by `scripts/verify_ground_truth.py`:
```bash
docker build -f competition_data/docker/Dockerfile.local \
  -t swebench-sandbox:local competition_data/docker
```

### Actual model-driven evaluations completed on 2026-10-08

The final comparison used real inference and the source-provenance-checked Docker verifier,
with identical 90/40/4/100 budgets, sampling, adapters, and image:

| Configuration | Resolved selected tasks | Decision |
| --- | --- | --- |
| Reviewed ZIP configuration | 3/5 | Reference baseline |
| Larger corrected prompt (`candidate_v2`) | 2/5 | Rejected |
| Narrow source-only contract (`candidate_v3`) | 3/5 | Prepared next candidate |

- The larger prompt changed `tests/test_adapters.py` in `requests_7315`, preventing the
  organizer's regression-test patch from applying. This was a real output-contract failure,
  not an unexplained dependency failure.
- All five narrow-candidate patches contained only the intended repository source file.
  It preserved the reference baseline's resolved tasks; it did **not** increase the measured
  resolution count. Changed-file checks appeared in some traces, not every trace.
- Remaining failures include FastAPI's exception contract and Rich returning `"FoO"` instead
  of the canonical `"foo"`. Do not treat input acceptance alone as complete feature behavior.
- This is a hand-selected set: three Requests tasks, one FastAPI, one Rich, no HTTPX.
  The narrow candidate was a later confirmation against the previously completed baseline
  on the same server/settings, not a fresh paired replicate. One sample at temperature 0.2
  does not establish a general performance gain.
- Local runtime: single A100, text-only, 64K context, vLLM 0.29.0, swegemma 0.2.7,
  adk-submission 0.2.12, adk-eval-core 0.1.0. This is not the scorer's 4x L4 environment.
- Full metadata, patches, traces, and grading output are preserved under
  `results/prompt_comparison_20261007/model_comparison_64k/` and `model_candidate_v3/`.
  Earlier eager and interrupted 32K runs are retained separately; they are not the final
  complete comparison.

### Public-API verification experiment completed on 2026-10-08

- Isolated candidate: `submission_build/verification_policy_20261008/submission.zip`,
  SHA-256 `5b75192b9f11469eaf73fad209cdf30b48ce9605264db87b3cc2b6d09d4f6064`.
  It differs from ref 56929785 only in three added verification-policy bullets in
  `prompts/system.md`: public-API output/state assertions, default/enabled option checks,
  and exception-contract checks that fail nonzero. No task-specific answers were added.
- All other member names and bytes match the submitted baseline. During this experiment,
  editable source and historical ZIPs were left unchanged. This candidate has **not** been uploaded.
- The exact extracted candidate ZIP compiled with installed organizer tools and default
  `SubmissionLimits`; the real `get_status` tool reported the unchanged 90/40/4/100 budgets.
  This is package/runtime validation, **not** a model-solving result.
- A new isolated Rich public-API probe found the preserved v3 patch returns `"pAuL"` rather
  than configured `"Paul"` for mixed-case input, including after an invalid-input retry.
  The reference patch passed both cases and the case-sensitive retry control.
- Fresh paired model runs resolved **3/5 baseline vs 2/5 candidate** under identical
  90/40/4/100 budgets, sampling, adapters and a rebuilt provenance-checked Docker image.
  **Do not promote this candidate.** The archived submitted source-only baseline remains unchanged.
- Candidate lost `requests_7427` with a timeout and failing emitted patch. Both configurations
  failed Rich grading and timed out on FastAPI without emitting a patch; neither FastAPI run
  reached patch grading. All eight emitted patches contained only intended source files.
- Rich candidate exercised `Prompt.ask`, but its assertions incorrectly required preserving
  input spelling (`"paul"`/`"PAUL"` for configured `"Paul"`). Grading observed `"FoO"` instead
  of canonical `"foo"`; public-API checks alone did not establish the right expected output.
- FastAPI candidate repeatedly called `edit_file` without mandatory `old_string`, despite
  explicit tool errors, until timeout. This fresh failure is tool-call reliability, not a
  graded exception-contract mismatch. Detailed evidence: `diagnosis.json` in the result directory.
- Requests, FastAPI and Rich reference-patch controls each passed in the new image.
  Every graded model patch retained snapshot import provenance. Controls are not model results.
- One sample per configuration on the same five hand-selected diagnostic tasks; baseline ran
  first. Single Spot A100, text-only 64K serving is not scorer hardware. This result does not
  establish a general causal effect of the prompt change.
- Full traces, patches, grading logs, input hashes and runtime metadata are retained under
  `results/verification_policy_20261008/paired/`; the reproducible runner, provenance plugin,
  image recipe, manifest and cost estimate are in its parent directory.
- Authorized temporary compute used a $20 budget and enforced two-hour VM runtime ceiling.
  The temporary VM, disk and snapshot were deleted after collecting evidence. The original
  VM remains terminated and its 300 GB disk is ready; raw checks are preserved in
  `results/verification_policy_20261008/cleanup.json`.

### Score-regression investigation and rejected recovery candidate, 2026-10-09

- Public scores changed from **0.12** (56893727) to **0.08** (56929785). This is not a
  task-level diagnosis. Earlier uploaded bytes remain independently unverified; local
  reviewed-baseline and source-only-v3 runs each resolved 3/5 selected tasks.
- Episode APIs returned empty lists for both completed submissions; the observed raw-output
  URLs returned HTTP 401 even through the authenticated SDK session. No task-level feedback
  was retrieved. API snapshots and probe results are in `results/score_regression_20261009/`.
- The submitted-configuration FastAPI traces include killed reproductions (exit 137);
  the fresh source-only baseline repeated the reproduction and timed out with no patch.
  The rejected verification candidate instead repeated malformed edit calls. Parsed traces
  cannot establish whether raw generation or the serving parser caused malformed arguments.
- `trace_audit.json` distinguishes configurations: the historical `pending` trace is the
  reviewed ZIP baseline, **not** source-only v3. It has two mandatory-`old_string` errors;
  submitted v3 and fresh source-only baseline have zero; the rejected verification candidate
  has 32 matching error observations. Do not misattribute these errors to the scored prompt.
- The archived recovery candidate added one failure-recovery
  policy: stop repeating unchanged killed/timed-out reproductions, use bounded verification,
  and correct edit arguments before one retry or a unique-match shell edit. No task-specific
  expected answers were added. All other submission members remain byte-identical to ref 56929785.
- Fresh artifact: `submission_build/failure_recovery_20261009/submission.zip`, SHA-256
  `dea621d29b9773e1c5e99098c1fb278283beabf04ed14e6adc8e6a1d43214719`.
  All ten member names and bytes were checked against editable source. The exact extracted ZIP
  compiled with organizer tools and default `SubmissionLimits`; genuine `get_status` reported
  unchanged 90/40/4/100 budgets. Compilation used **zero model requests**; the subsequent paired
  model evaluation below found no resolution gain. This candidate was never uploaded.
- A 10-second shell timeout bounds elapsed time, not peak memory, and prompt recovery rules
  do not prove a parser fix or correct semantic contracts. These remain evaluation risks.
- `evaluation_plan.json` freezes seven held-out tasks across all four repositories plus two
  diagnostic tasks, with interleaved configuration order and separate reporting. This small
  stratified set is not a statistically conclusive or proportionally representative score estimate.
  User authorized a new **$20 cap and three-hour VM ceiling**. An isolated Spot A100 clone,
  `gemma-recover-20261009-23383c` in `us-central1-c`, was started from a fresh snapshot;
  the original terminated VM and its 300GB disk remain untouched. No upload is authorized.
  The completed run was collected and its 211-file manifest verified before cleanup. The new
  VM, auto-deleted boot disk, and snapshot are absent; the original VM remains TERMINATED and
  its 300GB disk READY. See `cloud_cleanup_verified.json`. No billed-cost claim is inferred
  from the runner's `cost_usd: 0`, which does not represent GCP charges.
  Strict reference controls initially exposed dependency, TLS-fixture, and offline-network
  incompatibilities. Repairs are confined to the local verifier image/namespaces, not submission
  bytes or task tests; they do not establish scorer parity. Logs and smoke evidence are preserved.
  The reference patch for `fastapi_14186` produced 46 passed/6 skipped under Pydantic 2,
  but the grader required its explicitly Pydantic-1-only test to pass. The user authorized
  replacing it with the next seeded held-out FastAPI ID, `fastapi_15800`; nine tasks and
  strict unpatched/reference controls passed for all nine tasks before model inference.
- Complete paired results: baseline **4/7 held-out, 0/2 diagnostic**; recovery candidate
  **4/7 held-out, 0/2 diagnostic**, with identical resolved task IDs. All eighteen model runs
  completed grading. These are local model results, not public-score estimates.
  Counted tool calls increased **166 → 200**; recorded LLM calls **180 → 225**;
  mandatory-argument error observations **2 → 13**. Those observations include only actual
  rejected calls, not successful edit diffs containing the word "missing".
- Baseline patches were source-only **9/9**; candidate **8/9**. The timed-out `fastapi_15588`
  candidate left `update_sse_doc_v2.py` in its patch. No resolution gain and this output-contract
  failure reject promotion. Editable source was restored and byte-compared against all ten
  submitted-baseline members. Candidate ZIP and every run remain preserved.
- Semantic failures persisted: FastAPI self-inclusion used the wrong exception type; authentication
  changes missed exact headers/status/body contracts; SSE validation rejected bad values but
  used incompatible error messages; Rich case-insensitive acceptance returned `"FoO"` instead
  of canonical `"foo"`. These diagnose local failures, **not** the public 0.12-to-0.08 drop.
  Agent timeouts are tracked separately: the baseline HTTPX timeout still left a patch that
  passed real grading, and it remains a resolved task rather than being mislabeled a failure.
- Full evidence: `results/score_regression_20261009/completed_benchmark/paired/invocations/20261009T195155.973022Z/`,
  `paired_trace_audit.json`, and `paired_evaluation_decision.json`. Single samples at temperature
  0.2 and an A100/text-only server with local compatibility repairs do not establish scorer parity
  or statistical significance. The aggregate public-score drop remains causally unexplained.


### Historical reference-only records

The checked-in scripts validate **reference patches**, not model-generated patches:

- `scripts/verify_scoped.py` applies `task.patch` and `task.test_patch`, installs the snapshot
  locally, and runs pytest selected by added test-function names. Recorded result in
  `results/scoped_verify_summary.json`: **12 passed, 1 skipped** (`requests_7309`,
  `no_new_tests_detected`). It does not cover every changed-test pattern or full-file grading.
- `scripts/verify_ground_truth.py` passes `task.patch` directly to Docker verification.
  `results/ground_truth_verify/summary.json`: **3/13 resolved**, ten pytest exit-code-1 failures.
  The summary does not preserve their full test output; their causes are not established.
  This result does not establish a reliable or competition-equivalent local verifier.
- `results/smoke_test/task_results.jsonl` records one resolved task, `requests_7315`, with
  **zero patch bytes, zero LLM calls, and zero tool calls**. It is not an agent-solving result.
- Both scripts select direct instance-named `.tgz` snapshots. The historical review had only
  the **13 Requests tasks** locally; do not mistake that coverage for all public repositories.

Keep environment checks, reference-patch checks, and actual agent resolution rates separate.
Preserve complete verification output and import provenance when diagnosing failures.
Do not rerun historical failures merely to confirm them; investigate with a specific hypothesis.

### New strategy exploration and runtime refresh, 2026-10-09

- Live leaderboard check: Yurnero and Yike Xu **0.24**, Francis Joseph **0.22**. Our best
  historical score remains **0.12**; the later source-only submission is **0.08** and its
  exact-byte retry remains PENDING. No public evidence obtained establishes the leading teams' methods.
- Public [sampling/thinking/tool ablations](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/746250)
  report strong thinking and tool-budget effects, but single-run noise and different local hardware/budgets.
  [Teacher comparisons](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/747168)
  report 19/123 tasks flipping between repeated Gemma runs and triple-quoted edit-parser failures.
  These are other participants' reports, not our measured results or a leaderboard attribution.
- [Staff clarification](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/747248#3535945):
  none of the public training repositories occur in the hidden test set; staff reports all hidden
  gold patches pass. Repository-specific public-task fixes are not a reliable submission strategy.
- [Staff runtime update](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/747519#3535930)
  mentions tool-calling/thought-budget edge cases. Fresh wheelhouse files were downloaded separately:
  **swegemma 0.2.11, adk-submission 0.2.13, adk-eval-core 0.1.0**; its manifest lists
  **vLLM 0.19.1**. The previously evaluated environment remains 0.2.7/0.2.12/0.1.0 with
  vLLM 0.29.0. Dataset availability is not proof of the exact scorer deployment.
- Small fresh wheels and hashes are under `results/submission_strategy_20261009/`. An isolated
  source overlay launched the current CLI and compiled the byte-identical incumbent with actual
  organizer tools and both structural/generation constraint sets. No environment upgrade or GPU launch occurred.
- Three complete exploratory packages were frozen and compared member-by-member with their source:
  `context_fit_submission.zip` changes only output cap **16384 → 8192**, retaining thinking/sampling;
  `contract_first_submission.zip` forces a tool-free acceptance planner before the coder using
  `SequentialAgent`, `output_key: acceptance_contract`, and state injection. Additional coder YAML
  is required because workflow children accept config-path references, not inline agent dictionaries.
  The current compiler accepted all three; a real ADK Runner with deterministic offline model fixtures
  confirmed planner-before-coder state transfer. This tests scheduling, not Gemma solving quality.
  **Zero real model requests; all three unsubmitted and not promoted.** See `candidate_packages.json`
  and the smoke records. Editable source and historical submission ZIPs remain unchanged.
- Fresh compiler **0.2.13** also enables a distinct, single-field experiment:
  `thinking_without_history_submission.zip` keeps a positive 4096 thinking budget but sets
  `include_thoughts: false`. An intercepted actual compiled LiteLlm call proved **enable_thinking
  remains true and thinking_token_budget remains 4096**, while previous reasoning fields and returned
  thought parts are removed and visible response text is preserved. The response was an offline
  fixture, not model inference. Historical **0.2.12** would disable thinking with this setting;
  old thinking-summary ablations do not automatically establish its behavior on the fresh compiler.
  `thinking_history_wire_smoke.json` records both variants; `context_fit_wire_smoke.json` also
  confirms the lower cap reaches the provider as `max_completion_tokens: 8192`.
  Missing `thinking_level` was not a defect: the incumbent already enabled thinking.
- The organizer guide specifies a **32768-token** serving context; our latest paired run used
  **65536**. In the earlier measured boundary case, 18029 input + 16384 output exceeded 32768;
  reducing output reservation would fit arithmetically, but that is not a measured resolution gain.
- Staff also introduced a pending-submission limit, separate from the daily allowance:
  [queue update](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/747519).
  Retry ref 56976207 is now COMPLETE; recheck daily and pending allowances before any future upload.

### Fresh history-off screen stopped at the CPU gate, 2026-10-10

- New authorization: history-off first, **$20 cap**, **three-hour GPU ceiling**, stop if
  controls fail. No Kaggle upload was authorized. The fixed ID-only seeded selection is
  six previously unexposed FastAPI and six Rich cases; no failed-case substitutions.
- Baseline is the exact ref 56929785 artifact; candidate SHA-256
  `24a24f94b0fbe246c399602dbd0b558393aa02b8bc39e5d2ae04152836a33b5b`
  changes only `include_thoughts: true → false`. Editable submission source was not promoted.
- Fresh isolated Linux installation actually used swegemma **0.2.11**, adk-submission
  **0.2.13**, adk-eval-core **0.1.0**, Google ADK **1.36.1**, vLLM **0.19.1**,
  Transformers **5.13.1**, and Torch **2.10.0**. Exact SDK wheels were retained.
  Supplied runtime dependency constraints conflict: OpenTelemetry exporter 1.44 versus
  ADK's SDK ceiling, instrumentator 8.1 versus ADK's Starlette ceiling, and xgrammar
  0.2.5.post1 versus Transformers 5.13.1. Recorded local compatible overrides are exporter
  **1.41.1**, instrumentator **7.1.0**, and xgrammar **0.2.6**. This is not scorer parity proof.
- Both archives compiled with actual organizer tools on that Linux installation. Main and
  analyzer models retained `enable_thinking: true` and budget **4096** in both arms;
  only thought-history inclusion differed. Real serving/model-module imports loaded
  without initializing CUDA. No model or inference server was started.
- Real CPU grading showed trusted **unpatched failure / reference-patch success** for
  `fastapi_13920` and `rich_4075`. The run stopped on untrusted unpatched `fastapi_14356`;
  its reference control and the remaining selected cases were **not run**.
- That failure contains two new extra-list assertions plus twelve header snapshot
  failures/teardown reports. The 2026-10-11 diagnosis established that not all header
  failures were unrelated: a changed gold assertion also expects repeated `x-tag` values
  to become a list. Expected `Accept-Encoding` excludes `br`;
  actual HTTPX 0.28.1/Starlette TestClient requests include it. A separate real ASGI request
  inside the immutable image reproduced `gzip, deflate, br` and identified installed
  `brotlicffi`. No tests or headers were modified. A plain HTTPX client probe separately
  found missing `h11`; the working ASGI transport does not exercise that transport dependency.
- Archived dependency edges locate the decoder in the sandbox base:
  `pytest-httpbin 2.0.0 → httpbin 0.10.4 → brotlicffi 1.2.0.2`, not compatibility or
  SDK base injection. Remove both HTTPBin roots only from profiles whose actual test
  requirements do not need those fixtures; preserve Flask and a separate complete HTTPBin/TLS
  profile where required. Fixture requirements for all twelve cases remain unestablished.
- **Zero GPU allocations and zero model requests. No resolution gain was measured and no
  candidate was submitted.** Complete compiler, control, XML, dependency-lock and setup
  evidence is under `results/history_off_screen_20261009/`. Correct the fixture/dependency
  profile before another model screen; do not treat these CPU controls as solving rates.
- The uniquely named CPU VM, its new boot disk, and snapshot were deleted after evidence
  collection. Project-wide prefix queries found no remaining resources. Original
  `gemma-agent-dev` remains TERMINATED with its same 300GB READY disk retained.

### Grading-profile and negative-oracle repairs, 2026-10-11

- The exact-byte retry ref 56976207 scored **0.12**, while ref 56929785 scored **0.08**.
  Do not attribute this difference to a source change; no causal variance source is isolated.
- Direct streaming reads of all twelve fixed archives matched their previously recorded
  SHA-256 and sizes. Test trees, conftests and declarations contain no HTTPBin/Brotli
  dependency references. `direct_fixture_audit.json` and `profile_approval.json` preserve
  this basis; Flask remains installed as declared by FastAPI.
- Explicit `framework` and `httpbin` profiles now separate those fixture roots. The native
  framework image preserves Flask and ordinary HTTPX/httpcore/h11; actual HTTPX construction
  and Starlette ASGI GET returned `gzip, deflate`, with no Brotli or HTTPBin modules.
  Freeze/prepare profile mismatch rejection was also exercised on Linux.
- The corrected `fastapi_14356` negative control had **8 failed, 33 passed, 6 errors**:
  the remaining inline-snapshot teardown reports accompany the expected changed gold
  assertions. The former blanket error veto incorrectly rejected this valid negative oracle.
- The initial snapshot-specific repair passed eight real-SDK smoke scenarios but was
  superseded by a general **reference-first** protocol. `fastapi_14485` correctly raises
  `NameError: AsyncGenerator` during fixture setup on unpatched source, not an assertion.
  Its clean reference and expected negative error now form a trusted pair.
- Negative controls now require a clean reference in the same bound environment. Required
  gold tests must appear and not skip; failures or errors in changed gold tests may demonstrate
  the source bug. Errors outside changed gold tests and explicit PASS_TO_PASS failures remain
  rejected. No exception-name whitelist or stdout-error veto substitutes for structured JUnit.
  SDK bytes and positive/reference grading remain unchanged, including during manifest replay.
- The fixed run reached **eleven trusted pairs**. Final `rich_3486` reference had pytest
  **20 passed, 1 skipped, exit0**, but the actual SDK rejects the skipped required
  `test_traceback_finely_grained_missing`. The gold patch makes that test pre-3.11-only
  and `test_traceback_finely_grained` post-3.11-only; no Python version runs both.
  Do not fake the version, modify gold decorators, count the skip as a pass, or weaken the SDK.
- The original untrusted24-control manifest does not admit a GPU/model measurement.
  The user explicitly approved replacing the unscorable case. Before inspecting its gold
  patch or making any model request, the next untouched ID in the original seeded Rich
  ordering, `rich_3454`, was preregistered; the cohort remains six FastAPI and six Rich.
  Direct native archive audit confirms the replacement is framework-profile eligible.
  All24 native controls now pass against the amended plan; their complete148 hashed artifacts
  were verified after local collection. No model-solving gain is claimed.
  Complete evidence is under `results/history_off_screen_20261011/`.
- The replacement exposed a separate negative-attribution defect: its gold patch adds a URL
  parameter-table row, but SDK hunk extraction names the preceding `test_wrong_type`.
  Actual unpatched `test_highlight_regex[https://www.youtube.com/@LinusTechTips-spans38]`
  fails, while the reference passes. The negative predicate now normalizes pytest's tests-root
  module names and, absent explicit FAIL_TO_PASS, permits assertion failures in changed gold
  modules after a clean reference. Explicit requirements, required skips, unrelated errors,
  and all positive/model SDK grading remain strict. Ten native boundary scenarios passed,
  including PASS_TO_PASS rejection when FAIL_TO_PASS is absent.
- A new capped Spot A10040GB instance successfully ran vLLM0.19.1 on the prepared disk.
  Both actual LoRA aliases emitted reasoning; the real16-token probe closed the reasoning
  channel at exactly16 generated tokens. Its4096-budget comparison was naturally truncated
  by the probe's2048 output cap;2047 observed reasoning tokens are recorded as a lower bound,
  not a claimed4096-token termination. The probe now handles this boundary explicitly.
  `/server_info` required the version-documented `VLLM_SERVER_DEV_MODE=1`; the server
  was loopback-bound. Non-held-out probes are not solving-rate evidence.
  The complete paired twelve-case model screen has finished; GPU compute was stopped
  after5591seconds. No submission was authorized.
- The fresh guide still describes `include_thoughts: false` using old thinking-disable semantics.
  Actual compiler 0.2.13 behaves differently; independent scorer-deployment parity is unproven.

### Completed history-off model screen, 2026-10-11

- Twelve paired cases completed with all24 trusted controls. Baseline produced **7/12**
  verified patches; history-off produced **2/12**, with **zero gains and five regressions**.
  It fails the preregistered threshold of net≥2 gains and zero regressions: **reject, no upload**.
  No confirmation run was warranted and the submitted baseline/source was not changed.
- Agent completion is separate: both arms completed normally on **two** cases. Five baseline
  solves were actual passing patches salvaged after context errors, not normal completions.
  Context-limit terminations: baseline9, candidate6; session timeouts: baseline1, candidate4.
- The actual32K server reserves16384 output tokens; input beyond16384 therefore overflows.
  The failure's minimum16385 count is a server lower bound, not an exact recorded prompt length.
  Lower output reservation while retaining reasoning history is a prospective single-variable
  experiment, not a tested improvement or a shipped candidate.
- Direct trace checks identify operational failure paths, without proving thought-history causality.
  Candidate `rich_3454` attempted50 malformed `edit_file` calls after two successful tools;
  all lacked mandatory `old_string`, so no edit executed. In FastAPI14356/14301/9425,
  candidate traces contain no source-edit attempt before context termination. Candidate14301
  repeatedly sent `start_line"`/`end_line"` keys, not the proper range names; candidate14485
  introduced literal quote escaping and observed a SyntaxError at trace step26.
  These observations justify separate tool-format investigation, not a blind parser workaround.
  Recorded ATIF `elapsed_s` is cumulative session timing, not command duration.
- Several passing patches retained repository reproduction files despite the source-only prompt;
  candidate's solved `rich_3894` is among them. No patch modified tests. Gold-test success does
  not prove the scratch/output contract was obeyed.
- Before task inference, live admission exposed another stale assumption: plaintext
  `/server_info` uses `max_seq_len`, not `max_model_len`. The runner now reads the structured
  `?config_format=json` model configuration; exact live32K verification and the prior plain
  configuration hash binding both passed. No regex alias or weakened server check remains.
- Complete CPU, backend and model evidence is preserved in dated archives under
  `results/history_off_screen_20261011/`; all252 model artifacts and148 control artifacts
  were byte-verified. `submission_decision.json` separates verified patches from agent completion.
  These twelve cases are now model-outcome exposed; reuse is development confirmation,
  not fresh-held-out validation. One sample per arm and single-A100/current-SDK parity limits remain.
- The new CPU/GPU instances, cloned boot disk and snapshot were deleted. Prefix-filtered
  instance/disk/snapshot lists are empty. Original VM id8178724251330271494 remains TERMINATED;
  original300GB disk id7820791868839024902 remains READY. Settled billing was not queried.
- Live leaderboard leaders are **0.24**, next **0.22**, versus our best **0.12**.
  Public repository designs found during the run do not establish a leader's method or a
  causal gain. `public_strategy_findings.json` records their evidence limits and future
  exposure of `rich_3278`; exclude that ID from future model-outcome-unexposed selections.





### Output-reservation and repair-transaction experiments, 2026-10-12

- The frozen twelve-case development cohort completed a new native paired screen with
  all24 trusted reference/unpatched controls. All253 model-run artifacts were byte-verified.
  Baseline resolved **6/12**; changing only `max_output_tokens` from16384 to8192 also resolved
  **6/12**: gain `rich_3454`, regression `fastapi_14485`. **Reject the8K candidate; no upload.**
  Candidate task time increased from1965 to2479seconds. This is one sampled development
  run, not a held-out gain or an explanation of leaderboard-score variance.
- Normal completions increased from3 to6; baseline had9 context errors and3 passing patches
  salvaged after errors. The8K arm had2 context errors and4 session timeouts. Removing an
  output-reservation bottleneck did not improve the verified resolution count.
  Its failed `rich_4075` patch contained only `reproduce_issue.py`, violating the intended
  source-only contract. Successful patches in both arms contained repository source only.
- The isolated8K ZIP SHA is
  `25fb3d88fec3f243031f2da753d328a01c7db323c3dc9f7516a22243257337eb`.
  The submitted baseline and active `competition_data/sample_submission/` were not changed.
  Complete evidence is under `results/repair_transaction_20261012/`.
- A separate baseline-sampling candidate adds the native `repair-transaction` skill:
  bounded tracked-source locate/inspect, protected source-only unified-diff application
  with syntax-error rollback, and focused checks with bounded JSON and a1–60second timeout.
  ZIP SHA:
  `b8ee7279894c8c97481ddceae8ed019f204c756bf2e107918116ba9275130cd2`.
  Ten actual compiled-ADK/Docker scenarios passed using13 budgeted executor calls on a
  synthetic canonicalization fixture inside a restored Rich sandbox, including failing-before/
  passing-after behavior, traversal/test-path rejection, rollback, and timeout.
  This is runtime integration proof, not a model-solving or score-improvement claim.
- A Spot preemption occurred before task inference; the same capped GPU instance was restarted
  with a shorter stop duration. Initial and recovered windows remain within the authorized
  three-hour total. The later skill arm must be reported as reusing the verified same-run
  baseline, not a fresh paired replicate. `skill_run_admission.json` records the prospective
  full-arm admission estimate and unchanged resource deadline.
- The complete later skill arm resolved **4/12** versus the reused baseline's **6/12**:
  gain `rich_3454`; regressions `fastapi_14356`, `rich_3518`, `fastapi_14485`.
  All137 skill-run artifacts were byte-verified. **Reject the skill candidate; no upload.**
  Normal completions3, context errors7, timeouts2; one passing patch was salvaged after error.
  Actual skill loads occurred on5/12 tasks. Of17 script attempts,11 succeeded,5 returned
  patch-format/application warnings, and1 lacked `skill_name`. The skill did not reliably
  replace the legacy edit path; an invalid patch could still consume repeated model turns.
  In `fastapi_14301` step25, the model bypassed repeated rejected patches with `sed -i`;
  its passing grader result does not prove adherence to the transaction policy.
  Failed `fastapi_14356` emitted only `reproduce_issue.py`.
- Exact trace counting found15 rejected `edit_file` attempts in baseline `rich_3454`,
  seven in8K `fastapi_13713`, and one in8K `fastapi_14485`. Attempts rejected before execution
  differ from budgeted executor calls. `trace_tool_format_findings.json` preserves event IDs.
  Actual wheel argument-parser functions round-trip canonical native regex and skill-array
  payloads; ordinary JSON string syntax is not the Gemma4 wire format. Raw model emissions
  were not captured, so this does not establish a server parser defect.
- Some task statements supply only a terse PR description and issue URL. Host inspection of
  linked Rich issue3014 reveals the control-code reproduction absent from the supplied
  `rich_3471` statement. Both checked-in harness guides document an air-gapped sandbox:
  do not propose live issue fetching or inject manually retrieved case answers into a candidate.
  `diagnosis_and_next_experiment.json` records these limits and the unmeasured behavior-probe idea.
- `submission_decision.json` binds all three exact archive hashes and rejects both candidates.
  It proposes a separate compact, revision-bound edit workflow whose executor generates
  diffs, rather than requiring model-authored hunk counts. This is not yet implemented or measured.
- New CPU/GPU instances, cloned disk and snapshot were deleted; all three prefix-filtered
  resource lists are empty. GPU running time, including the preempted first start, was
  **8324.54seconds**, below the authorized10800. Original VM id8178724251330271494 remains
  TERMINATED; original300GB disk id7820791868839024902 remains READY.
  The conservative estimate is$18.24 within the authorized$20 envelope, not settled billing.
  Exact smoke drivers/parser sources were archived before removing standalone throwaway files.

### Compact revision-bound editing experiment, 2026-10-13

- The isolated candidate in `results/revision_bound_edit_20261013/` replaces model-authored
  unified diffs with literal UTF8 replacements against a full-file SHA256 revision and
  inclusive line bounds. Insertions, range deletion, guarded file creation/removal, pre-write
  Python validation and atomic installation are implemented. Single-writer execution is
  assumed; revision checks do not synchronize noncooperating concurrent writers.
- ZIP SHA:
  `b9782f1c0d175f1ae1785a020eaf4db8183bb2b4ab6b19e400f506200f3a7ea6`.
  All eight archive members match source. Sampling,90/40/4/100 budgets and main adapter are
  byte-identical to the baseline; root prompt/tool workflow changes are a bundled intervention,
  not isolated causal tests of its components. Analyzer files and unused tool adapter are removed.
- Actual0.2.13 SDK offline compilation exposes exactly `submit_patch` plus the four native
  skill tools. Shell/legacy file writers and analyzer are absent. Both arms retain output16384,
  thought history and the official4096-budget bridge; candidate compiles main_lora only.
  Character/schema footprint is recorded, not invented token counts.
- Ten direct CLI scenarios passed. CR-only source exposed a generated-preview mismatch with
  Git line semantics; the corrected LF-based diff preview passes real reverse-apply validation.
  Invalid syntax and stale/no-op/protected edits leave dirty bytes intact; rejection before
  writing is not falsely labeled rollback.
- The user separately authorized a new$20 controlled screen, at most3GPU hours/2CPU hours,
  no upload, preserving the original disk and deleting only new resources. Prefix:
  `gemma-revision-20261013-864358`. The provider snapshot is READY despite the initial
  client command timing out. CPU admission requires the actual rich_3454 SDK smoke and all24
  fresh trusted controls before any GPU task inference. No solving gain is established by
  direct CLI or compiler proof.
- Native admission found a real helper defect: one tracked symlink aborted the entire locate
  operation. Unsafe paths now remain inaccessible but are reported/skipped during search.
  The initial ZIP is preserved as `candidate_initial.zip`; corrected ZIP SHA:
  `8f69efd70fbdffa8924f10d60a1117fd0f98cb838bc137b7b172af79bd3f440b`.
  Fresh compiler/control admission is required for these changed bytes; the initial
  controls are retained, not silently rebound to a different artifact.
- Corrected ZIP admission completed: all24 real controls trusted and all148 control artifact
  hashes checked after retrieval; actual native SkillToolset/executor smoke passed29 scenarios
  and168 assertions on restored rich_3454. It made zero model calls and removed its container.
  The smoke includes stale revisions, syntax rejection before mutation, mode/dirty-byte
  preservation, symlink/traversal protection, canonicalization and creation/removal.
  Two failed smoke-driver attempts are preserved. This establishes runtime behavior,
  not a model resolution-rate gain.
- The complete32K paired attempt is retained in `model_comparison/`, not accepted as a clean
  workflow comparison:20 agent context-window errors and2 session timeouts occurred across24
  rows. Baseline graded5/12 (3 salvaged after agent error); candidate graded3/12 (all salvaged).
  Fixed16384 output reservation left at most16384 input tokens on that local server.
  No submission recommendation follows from this infrastructure-limited attempt.
- Local capacity re-admission changes both arms to65536 context without changing either ZIP,
  sampling or task budgets. CPU controls never run inference: their original32K metadata
  and manifest bytes remain intact, all non-server selection identities remain strict, and
  the approved plan explicitly separates `cpu_control_server` from the live model-run
  server. A fresh live backend proof is mandatory; no control output is fabricated or rebound.
- Fresh primary staff clarification was read on2026-10-13:
  https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743573 .
  Staff directs custom Python tools to skill scripts executed in the sandbox. It does
  not establish a supported competitor-defined host ToolRegistry function import.
  The rendered page text is preserved in `custom_tools_staff_clarification.json`.
  This constrains typed-custom-tool proposals; it is not evidence of leaderboard leaders' methods.
- Capacity-corrected full screen completed all24 paired rows in `model_comparison_64k/`,
  with zero context-window errors and clean native cleanup. Baseline resolved7/12
  (5 normally completed,2 salvaged after agent timeout); candidate resolved2/12
  (1 normally completed,1 salvaged). One gain: rich_3454. Six regressions: fastapi_14356,
  fastapi_14485, fastapi_9425, rich_3518, rich_3894, rich_4075. **Rejected for submission.**
  This is one stochastic sample on the already exposed development set, not a hidden-score estimate.
- All twelve actual candidate compilation observations expose exactly the five intended tools.
  The narrower schema did not make the workflow easier for this model:258 script calls,
  81 non-successful responses,61 replacement attempts and14 applied edits. Failures include
  nested argument arrays, invalid revisions/bounds, prohibited test edits and32 syntax
  rejections. Raw request/response capture is needed before attributing transport problems
  to the parser. No escape stripping or guessed fallback is introduced.
- A normal candidate completion on rich_3471 still failed the actual consumer regression:
  it added optional/None token handling rather than fixing control-character span lengths;
  `Text.divide` raised IndexError. Tool-runtime correctness is not issue correctness.
- Exact measured runners/probes/plans are archived in `model_screen_reproduction_sources.zip`;
  current replay CLI reads the explicit recorded32K/64K plan rather than hardcoding capacity.
  Both plans were exercised through actual offline SDK compilation after that maintenance.
  Full traces, patches, test output, import provenance and per-task contracts are preserved.
  Decision and workflow counts: `submission_decision.json`, `workflow_analysis_64k.json`.
- The provider's requested3-hour GPU stop completed47.274seconds beyond3hours measured from
  VM start; no GPU restart was performed. A separate bounded CPU-only clone retrieved the
  completed output after shutdown. All new prefix-matched instances/disks/snapshots were
  deleted and freshly listed empty. Original VM remains TERMINATED with its original300GB
  disk and provider IDs intact. Billing is not independently settled by runtime evidence.
- Editable submission source and accepted historical ZIP remain unchanged; no upload.
  Next evidence-driven direction: retain native typed tools and isolate argument/newline
  transport and behavior-probe capability, not another bundled restricted editing workflow.

### Native consumer-reproduction experiment, 2026-10-13

- Full evidence: `results/consumer_verification_20261013/`. Frozen candidate SHA
  `e7db4e441ab80d3282f43f9fe76267380457779468d3a091d7e248b52cb750de`
  changes only three system-prompt bullets: reproduce the actual issue before editing,
  then rerun the same consumer check. All ten native main tools, four analyzer tools,
  adapters, sampling and90/40/4/100 budgets remain unchanged.
- Fresh CPU admission passed all24 development reference/unpatched controls and178
  native smoke assertions. Actual Rich3471 consumer rendering changed from IndexError
  to the expected wrapped output; FastAPI13920 changed from HTTP422 to200 with
  `"value: 123"`. These reference-patch controls establish probe capability, not model success.
  A missing final LF in raw reference patches was repaired only in the smoke driver's
  transport framing; successful controls were not repeated or rebound.
- Complete alternating paired64K model screen: baseline8/12, candidate7/12,
  no gains and one regression, fastapi_9425. **Reject; no upload.**
  Baseline had8 normal resolutions and4 agent timeouts; candidate had4 normal
  resolutions,3 passing patches salvaged after timeout, and8 agent timeouts total.
  This is one sample on previously exposed development tasks, not hidden-score evidence.
- The regressed candidate generated a repository `repro.py` using ordinary `-> None`,
  missed the specified stringified annotation, and emitted no implementation fix.
  Baseline changed `get_typed_return_annotation` and passed the real organizer test.
  Raw command reuse is not workflow proof: Rich3454's failure-to-pass pair changed a
  test expectation (restored before submission); FastAPI13713's before failure was
  an agent-introduced NameError after editing. Neither proves faithful initial reproduction.
- Separate14-request raw transport diagnostic completed:12 auto choices plus2 forced
  controls. Eight API arguments matched the requested literals; SDK conversion preserved
  all14 API argument objects. No parser defect was proven. Independent extraction of
  the multiline native command shows missing Python quote escapes already present in
  generated raw text, unchanged by API parsing and SDK conversion. This does not
  attribute every other mismatch or establish scorer/server parity.
- Prospectively frozen optional six-case confirmation was not run through the model.
  Development promotion failed; rich4006's unpatched control also timed out without
  JUnit. Its reported issue is an infinite loop in split_graphemes, consistent with
  the timeout but not proof of the exact stalled test. No case substitution or trust bypass.
- Parent verified all24 compiled native contracts, both ZIP/source member sets,
  48 raw trace/command hashes and142 transport artifact hashes. Full patches, logs,
  JUnit, generated token IDs, HTTP bytes and parser/SDK source are retained.
  Exact reproduction helpers are archived in `experiment_reproduction_sources.zip`.
  The full247-wheel dependency closure and immutable grading image are preserved locally.
- GPU start-to-stop6196.375seconds, below the authorized3hours; no restart. Only new
  identity-checked GPU VM, clone disk and snapshot were deleted; fresh prefix lists empty.
  Original VM remains TERMINATED with its original300GB disk and provider IDs intact.
  Runtime is not settled billing. Editable submission and historical artifacts unchanged.
- Next unmeasured hypothesis: reduce thinking budget4096 to1024 while retaining the
  incumbent prompt, native tools, thought history and16384 output cap. Both Rich3506
  arms used roughly7.3–7.5K completion tokens without emitting a source patch; baseline
  made only4 tool calls before timeout. This is distinct from the rejected8K output cap;
  faster reasoning may permit implementation but may sacrifice reasoning quality.

## Planned work, not demonstrated progress

The earlier roadmap proposed scaffold iteration, trajectory generation, LoRA SFT,
rejection-sampling rounds, packaging, and a paper-track writeup. These are plans, not evidence
that training or later phases have occurred. Query Beads for current task status:
```bash
bd list -l gemma4-swe
```

Trusted twelve-case controls and completed history-off and8K paired screens are now established.
Next priorities:
1. Test the isolated thinking-budget hypothesis above against the incumbent; keep tool schemas,
   prompt, output cap and history fixed. Measure verified resolutions and normal completions,
   not merely more tool calls. Raw diagnostic evidence does not justify a guessed parser repair.
2. Test a repository-independent behavior-probe agent using the issue and bounded source slices.
   Derive API-equivalence checks and local invariants, not gold tests or manually supplied answers.
3. Use protected, previously unexposed cases and repeated paired runs; change one intervention at
   a time, preserve exact artifacts, and require material resolution gains without output-contract regressions.
4. Justify fine-tuning with verified trajectories and held-out transfer gains; current LoRA B matrices
   are zero, so the preserved adapters are not evidence of training.

Training should be justified by verified trajectories and held-out evaluation, not assumed to
be the next source of gains. Update this file when results establish or overturn a hypothesis.

## Submitting

```bash
kaggle competitions submit -c gemma-4-developer-agent \
  -f submission_build/source_only_retry_20261008/submission.zip \
  -m "Exact-byte retry of 56929785 after Kaggle system error; source-only guard, budgets and sampling unchanged"
```
Check live allowance before submitting: the Kaggle API's
`competition_get_submission_limits("gemma-4-developer-agent")` returns `numAllowedNow`.
History alone is insufficient: ref 56929785 errored and an additional submission was allowed
on the same UTC day. After retry ref 56976207, the CLI reported zero remaining.
The command above identifies the accepted exact-byte retry. For a future candidate, build and
verify fresh bytes and use a new dated upload directory with basename `submission.zip`.

### Public-recipe adoption and scorer-parity screen, 2026-10-14

- **Submitted ref 57163806**, SHA-256
  `a9d2a86d759299fdca9cd8010aac3636f9fd3f39c5325ea992cf99806f8e935a`, built from the public
  notebook `honghanhhh/gemma-4-baseline-lb-0-24` (Apache-2.0 lineage via
  `verracodeguacas/gemma-4-agent-budget-fit-single-agent`) by parsing its `FILES` literal with
  `scripts/build_from_notebook.py`; the notebook was never executed. Single agent, no analyzer
  and no graph tools, 240/28/8/80 budgets, `max_output_tokens` 8192, thinking 4096 with
  history. Artifacts and compile receipt: `submission_build/public_recipe_20261013/`.
  PENDING at session end — recheck before claiming a score.
- Our prior incumbent differed from that recipe on nearly every lever: `timeout_seconds` 90 vs
  240, output cap 16384 vs 8192, 4 vs 8 agent minutes, 40 vs 28 calls, analyzer plus graph
  tools vs neither. **`timeout_seconds` also bounds the grader's pytest run**
  (`swegemma/harness/verification.py`), and 74 of 114 sound public tasks need more than 90 s
  for the gold patch alone, so the incumbent's 90 s could fail correct patches.
- **swegemma 0.2.11 was silently re-released on 2026-10-12** (wheel sha `9ad87658…` vs our
  earlier `63f054a3…`). It adds `verification_timeout_seconds` (default 300), which decouples
  grading pytest from `timeout_seconds`. Preserved at `results/runtime_20261012_wheel/`.
  Re-download the wheelhouse rather than trusting a cached version number.
- The 2026-10-12 starter notebook shows the scorer's ADK context settings:
  `EventsCompactionConfig(15, 2, 14336, 5)` and `ContextCacheConfig(2048, 1800, 10)`, with
  vLLM `max_model_len=32768`. Earlier local screens used 64K and no compaction, so their
  context-overflow findings do not describe the scorer.
- **Completed 95-task paired screen at scorer parity** (32K, starter compaction, 9.05 s/model
  call against Kaggle's measured 8.68 s on 4xL4): recipe **37/95**, temperature 1.0 + top_k 64
  **35/95** (4W/6L), thinking 2048 **38/95** (6W/5L), edit-recovery prompt line **39/95**
  (7W/5L). All inside noise at one sample per arm; **no promotion, no bytes changed**.
  Public reports of a temperature-1.0 gain did not reproduce. Full evidence, limits and the
  task mask: `results/eval_matrix_20261014/RESULTS.md`.
- The dominant failure across all four arms is a non-empty patch that fails the hidden tests
  (28-42 of 95), not budget exhaustion. Budget tuning cannot address it.
- 380 graded runs with traces and patches are preserved under
  `results/eval_matrix_20261014/out/`; 149 are resolved. This is the first local corpus of
  Gemma trajectories usable for fine-tuning.
- Reusable runners are in `scripts/eval_matrix/` (per-task process, interleaved resumable
  matrix, gold/empty controls, paired sign test). `serving_requirements.lock` rebuilds the
  251-package serving environment from PyPI except 34 wheels that must come from the preserved
  official wheelhouse (they are not byte-identical to PyPI).
- 2.59 GPU-hours on 4xA100 Spot (one preemption, resumed) of the authorized $100, about $13.
  All new resources deleted and verified absent; original VM/disk untouched.

### Score, failure anatomy and plan to 0.30, 2026-10-15

- **Ref 57163806 scored 0.15.** The public LB is 58 tasks scored `floor(k/58 × 100)/100`: every
  one of the 14 distinct scores across 2,809 teams lies on that lattice, so 0.15 = 9/58, the
  19-team 0.22 cluster = 13, the two 0.24 leaders = 14, and **0.30 requires 18/58**. Identical
  bytes vary by SD ≈ 2 tasks (public ledgers and our own 0.08→0.12 pair).
- The prompt we submitted was a since-replaced honghanhhh revision; the notebook is now "v3" =
  flexonafft `budget-aware-coding-agent-v2` (the 0.22 cluster) + three prompt edits. Both rebuilt
  byte-exact: `submission_build/flexonafft_v2_20261015/` and `submission_build/honghanhhh_v3_20261015/`.
  `scripts/build_from_notebook.py` now resolves `json.loads` and variable-referenced FILES.
- **Failure anatomy of the 380 preserved runs** (details in `HANDOFF.md` 2026-10-15): tasks are
  bimodal (26 always, 47 never, 22 flip; pass@4 48/95); resolve rate collapses with gold-patch size
  (≤5 lines 21/32 … >100 lines 0/12); A arm's 58 failures split 16 right-file-wrong-fix / 9
  partial / 11 wrong file / 9 import-breaking / 13 empty, with zero regressions. `edit_file`
  succeeds on only 57% of calls — 31% arrive malformed because `old_string` is shredded on `:` by
  the tool-call serialization (A 62%, B 50%, C 48%, D 71%) — and `write_file` on 7% (155/201
  rejected `/tmp` paths). 27 of 56 empties attempted their first edit only after the 28-call cap.
- **Plan**: T0 re-anchor (submit v2 byte-exact, expect 12–13/58; local A vs v2 vs v3 to calibrate
  the local↔public exchange rate), T1 tool-call reliability arm (drop `write_file`, heredoc-first
  edits for colon-containing targets, edit by call 8), T2 `SequentialAgent` reviewer stage, T3 LoRA
  rejection-sampling SFT (harvest ~620 runs, Fireworks SFT on `gemma-4-31b-it`, gates G1–G3,
  fallback to the bf16 QAT twin), T4 submission discipline. Public sweeps show sampling and
  thinking-budget knobs are noise; thinking off halves the score.

### T0a anchor upload and T0b/T1 matrix, 2026-10-15 (later the same day)

- **Uploaded flexonafft v2 byte-exact as ref 57214360** (zip sha `53714f0e…`, compile-checked
  with swegemma 0.2.11 / adk-submission 0.2.13); PENDING at session end.
- **760-run scorer-parity matrix** on 4× A100 Spot (us-central1-a after two preemptions in -c and
  nine on-demand stockouts): T1 112/285 (39.3%) vs V2 107/285 (37.5%), paired 18W/13L, +5,
  p = 0.47 — **not promoted**; V3 38/95; A_recipe 35/95 (37 on 10-14). Identical V2 reruns scored
  37/31/39: local SD ≈ 3 tasks per sample. T1's mechanics confirmed (malformed edits 29% → 6%,
  timeouts 64 → 51/285) but empties 32 → 41 and wrong patches 81 = 81. All prompt/tool variants
  are one 36–40% band; the lever left is T3 training, harvesting with T1's clean protocol.
- Tooling added: `remote_bootstrap.sh` (setup/serve/matrix/resume), `run_round.sh`,
  `spot_watchdog.sh`, `mechanism_check.py`, `split_lock.py`, `make_t1_arm.py`,
  `scripts/rft/build_sft_jsonl.py` (resolved traces → OpenAI tool-calling SFT JSONL; 149 → 49
  clean on the 10-14 corpus). Evidence: `results/eval_matrix_20261015/`.
- Launch bugs fixed: wrong `swegemma-0.2.11` build (`63f054a3…`; use `9ad87658…` from
  `results/runtime_20261012_wheel/`); macOS AppleDouble files in arm trees (build bundles with
  `COPYFILE_DISABLE=1`); organizer `vllm==0.19.1`/`safetensors==0.8.0` wheels come from
  `results/consumer_verification_20261013/deployment.tar`.
- ≈24 GPU-h (~$30–35) of the authorized ~45; all matrix resources deleted and verified absent;
  original VM/disk untouched.

### T3 LoRA v1: harvest, training, gates, 2026-10-15/16

- **Harvest:** 570 runs (T1 at temperature 0.7, 6 × 95), 218 resolved; `sft_train.jsonl` 113 clean examples / 33
  training tasks, `sft_eval.jsonl` 38 / 19 held-out (`results/harvest_20261015/`).
- **Fireworks managed SFT failed four times** ("Internal error"): the Gemma 4 chat template needs tool-call
  `arguments` as JSON objects (fixed), yet attempt 4 failed too → self-hosted.
- **Self-hosted LoRA** (`scripts/rft/train_lora.py`, bf16 QAT twin sharded over 4× A100-40GB, r=32 on the text
  decoder, 90 examples at a 20K cap, 2 epochs): held-out token loss 0.458 → 0.138. Preempted once; resumed.
- **Gates:** adapter loads under vLLM on the w4a16 model (TP=1 needs 1 slot/rank 32 — the scorer's 8/128 starve the
  KV cache); G1 8/12 with zero malformed calls; **held-out screen 38×3 paired: 29 vs 39 of 114, W5/L15, net −10,
  p = 0.041 → not promoted.** Cause: longer, slower generations → more empty-at-budget runs. v2 ideas in
  `results/harvest_20261015/GATES.md`. ≈ 8 Spot VM-hours (~$40); snapshots kept, VM/disk deleted.
