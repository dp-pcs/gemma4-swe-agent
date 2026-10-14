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
