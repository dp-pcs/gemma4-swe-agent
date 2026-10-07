# AGENTS.md — Gemma 4 Developer Agent Competition

Background and intent for any agent (human or AI) picking up this repo. Read this before doing anything else.

## What this is

Kaggle competition **"Google - The Gemma 4 Developer Agent Competition"**
(`gemma-4-developer-agent`, https://www.kaggle.com/competitions/gemma-4-developer-agent).

Goal: build an autonomous SWE agent (powered by Gemma 4) that resolves real GitHub issues
(SWE-bench-style tasks) by producing a patch that passes the issue's hidden tests. Scored on
**resolution rate** = resolved tasks / total tasks.

- Deadline: **2026-12-02**
- There's also a companion paper-track competition (`gemma-4-developer-agent-paper`, due 2026-11-12)
- Beads label for all related issues: `gemma4-swe` (global hub, `bd list -l gemma4-swe`)
- 129 public training tasks, ~120 hidden tasks used for scoring
- **1 submission per day**, daily counter resets at 00:00 UTC
- Global 12-hour execution cap across all hidden tasks per submission (exceeding it currently
  errors the whole submission)

## Current status (as of 2026-10-07)

- **Submitted**: `submission_build/submission.zip` uploaded 2026-10-07 00:01 UTC
  (Kaggle ref `56893727`). Status was still PENDING as of last check — check with:
  ```bash
  kaggle competitions submissions -c gemma-4-developer-agent
  ```
- **Baseline score**: the unmodified starter-kit submission scored **0.03** (3% resolution rate)
  when run with the starter kit's default 1-min/10-tool-call budget. That tight budget was
  almost certainly starving the agent — see Eval Budgets below.
- **What's in the current submission** (improvements over the starter kit):
  - `eval_config.yaml`: budgets raised from `timeout_seconds:60 / max_tool_calls:10 /
    max_time_minutes:1 / max_turns:50` → `timeout_seconds:90 / max_tool_calls:40 /
    max_time_minutes:4 / max_turns:100`
  - `prompts/system.md`: added budget-awareness (`get_status` every 5 calls, submit immediately
    if <90s remain), conditional `code_analyzer` delegation, `/tmp` scratch-file guidance,
    partial-fix-is-better-than-nothing framing
  - `prompts/analyzer.md`: strict structured output format (Root Cause / Target / Recommended
    Change only), explicit shared-budget note
  - `agent.yaml`, `configs/sampling.yaml`: unchanged from starter kit
  - LoRA adapters (`main_lora`, `tool_lora`): still the starter kit's **dummy/random-init**
    adapters — no real fine-tuning has happened yet (that's Phase 3)

## Repo layout

```
competition/
├── AGENTS.md                  # this file
├── kaggle_provided/           # organizer-provided reference (don't edit)
│   ├── HARNESS_README.md      # THE spec — read this for anything about the eval harness
│   ├── tasks.jsonl            # 129 public tasks
│   └── sample_submission/     # original unmodified starter kit
├── competition_data/           # local working copy, extracted + has our edits
│   ├── sample_submission/     # ⚠️ THIS IS WHERE WE EDIT — prompts/, eval_config.yaml etc.
│   │                          #    (confusingly named "sample" but it's actually our working copy)
│   ├── snapshots/, embeddings/, graphs/  # task repo snapshots + code-intelligence data (gitignored, large)
│   └── docker/                # sandbox Dockerfile
├── submission_build/
│   └── submission.zip         # BUILT ARTIFACT — zip of competition_data/sample_submission/
│                               #   + anything staged in /tmp/submission_stage. Rebuild after
│                               #   editing source (see "Rebuilding the submission" below).
├── scripts/
│   ├── verify_ground_truth.py # applies ground-truth patches, runs harness, sanity-checks scoring
│   └── verify_scoped.py       # faster local check: ground-truth patch + scoped pytest, no docker
├── results/                   # local eval run outputs (smoke tests, verify runs)
├── gcp_setup*.sh               # VM bootstrap scripts (model download, venv, docker image build)
└── wheelhouse/                  # pip wheels for swegemma/adk-submission/adk-eval-core/vllm (gitignored)
```

**Known wrinkle**: there's no clean separate "our submission source" directory — edits happen
directly in `competition_data/sample_submission/` (which doubles as the organizer's starter kit
AND our working copy). To rebuild `submission.zip` after editing:
```bash
mkdir -p /tmp/submission_stage
unzip -o submission_build/submission.zip -d /tmp/submission_stage/
cp competition_data/sample_submission/eval_config.yaml /tmp/submission_stage/
cp competition_data/sample_submission/prompts/*.md /tmp/submission_stage/prompts/
# ...copy over whatever else changed...
cd /tmp/submission_stage && zip -r /path/to/competition/submission_build/submission.zip .
```
Always verify after rebuilding: `unzip -p submission_build/submission.zip eval_config.yaml`

## Eval budgets (don't regress these)

Per `kaggle_provided/HARNESS_README.md` §7.1 and Kaggle staff replies in the competition
discussion forum:
- `timeout_seconds` = per-shell-command timeout (not per-task). Default 300s is too forgiving;
  we use 90s to kill runaway test runs before they eat the whole time budget.
- `max_time_minutes` = **pure agent-loop time** — container setup (snapshot extraction, wheel
  install, docker bootstrap) is excluded from this budget, so it isn't as tight as it looks.
- Global math: 12h cap / ~120 hidden tasks ≈ 6 min/task average *including* setup. Setup costs
  ~1-2 min, leaving ~4-5 min of real agent time per task. We set `max_time_minutes: 4` to leave
  margin (exceeding the 12h cap currently **errors the entire submission** — a fix to score
  partial runs as 0 instead was reportedly planned but unconfirmed as live).
- `max_tool_calls: 40` is generous on purpose — time should be the binding constraint, not call
  count.

## GCP dev VM

Instance `gemma-agent-dev` (project `ai-coe-454404`), originally `g2-standard-24` (2x L4, 46GB
VRAM) in `us-west1-a`. Disk has: Gemma 4 QAT model (~22GB), full `swegemma`/`vllm` venv, built
Docker sandbox image, `competition_data/`.

**Status as of 2026-10-06**: VM is **TERMINATED**, disk persists (~$30/month, 300GB
pd-balanced). us-west1-a (and every other zone checked: us-west1-b/c, us-central1-a/b,
us-east1-b, us-east4-a) was in **L4 GPU STOCKOUT** for both 2x and 4x L4 configs — could not
restart the VM at all, let alone upgrade to 4x L4 to match Kaggle's scoring environment.
Check current availability with:
```bash
gcloud compute instances start gemma-agent-dev --zone=us-west1-a
```
There's a weekly reminder (`bd recall gcp-idle-disk`) to check whether this disk is still
needed — **delete it if the competition is paused/done** (`gcloud compute disks delete
gemma-agent-dev --zone=us-west1-a`), otherwise it bills quietly forever.

**Known vLLM issue on 2x L4 (TP=2)**: vLLM 0.29.0 + Gemma4 (multimodal) + tensor_parallel_size=2
crashes during vision-encoder warmup with `ncclInvalidUsage` on a `torch.distributed.all_reduce`
call. Root NCCL init was fixable with `VLLM_DISABLE_PYNCCL=1 NCCL_IB_DISABLE=1 --enforce-eager`,
but the warmup-phase crash persisted through `--disable-custom-all-reduce` too. Likely specific
to TP=2 + this model's multimodal encoder; Kaggle's real scoring env uses TP=4 and presumably
doesn't hit this. **Don't assume 2x L4 will work for a full local eval** — budget for either
getting 4x L4 capacity or using Kaggle's daily submission slot as the eval mechanism.

**Fireworks AI was evaluated as an alternative and rejected**: no QAT variant of the model
hosted, no custom LoRA adapter injection on hosted inference, and uncertain tool-call-format
compatibility with the harness's `tool_call_parser='gemma4'`. Not worth pursuing unless the
model variant and LoRA requirements change.

## Roadmap (beads issues, label `gemma4-swe`)

```bash
bd list -l gemma4-swe
```
- Phase 0: Repo + infra setup — **in_progress**
- Phase 1: Baseline zero-shot agent scaffold + eval — in progress (this submission)
- Phase 2: Scaffold iteration for pass-rate gains — next
- Phase 3: Trajectory generation + LoRA SFT on Fireworks
- Phase 4: Rejection-sampling fine-tuning rounds
- Phase 5: Harden + package submission
- Phase 6: Paper track writeup (due 2026-11-12)

## Local validation before spending a submission

Only 1 Kaggle submission/day — validate locally first where possible:
- `scripts/verify_scoped.py` — fastest signal, no docker, applies ground-truth patch + scoped
  pytest on just the new/changed tests. Last run: 12/13 passed.
- `scripts/verify_ground_truth.py` — full docker-based harness check against ground-truth
  patches, confirms the scoring pipeline itself works correctly.
- Full local `swegemma eval` run against the agent (not ground truth) requires the GCP VM with
  working vLLM — see GCP section above for current blockers.

## Submitting

```bash
kaggle competitions submit -c gemma-4-developer-agent \
  -f submission_build/submission.zip \
  -m "description of what changed"
```
Check daily limit before submitting — `kaggle competitions submissions -c gemma-4-developer-agent`
shows submission history; if the most recent one is from today (UTC), the slot is used.
