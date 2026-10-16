# LoRA v1 (swe_rft_h1) gate results — 2026-10-16

## Verdict: not promoted

| Gate | Result |
| --- | --- |
| G1 load | PASS — adapter (r=32, bf16, 490 MB) loads under vLLM on `gemma-4-31b-it-qat-w4a16-ct` (TP=1, 1 slot, rank 32); KV cache 16.2K tokens |
| G1 smoke (12 held-out tasks) | 8/12 vs untrained expectation ≈ 8.7; **0 malformed tool calls**, landed edit in 11/12, median first edit at call 7 |
| **Held-out screen (38 tasks × 3 samples, paired)** | **G1_lora 29/114 (25.4%) vs T1_toolfix 39/114 (34.2%); W 5 / L 15, net −10, sign-test p = 0.041** |

Per sample: T1 15 / 14 / 10, adapter 11 / 8 / 10 of 38. The pre-registered bar was net ≥ +9 to submit, net ≤ −9
to hold; the adapter is clearly worse on tasks it never trained on, so it is **not submitted**.

## What the adapter learned, and what went wrong

Token-level learning was real: held-out eval loss 0.458 → 0.163 (epoch 0) → 0.138 (epoch 1), and tool-call
formatting was flawless. But task resolution fell because the agent became **slower and more hesitant to
edit** under the 8-minute / 28-call budget:

| | T1_toolfix (untrained) | G1_lora (adapter) |
| --- | ---: | ---: |
| resolved | 39 | 29 |
| empty patch at budget | 38 | **55** |
| wrong patch at budget | 24 | 21 |
| wrong patch, budget left | 13 | 9 |
| runs that hit the cap (≥470 s or 28 calls) | 78 | **91** |
| median wall | 445 s | **495 s** |
| median tool calls | 22 | 21 |
| tokens per model call | 305 | **370** |
| seconds per model call | 14.8 | **17.6** |
| heredoc edits (3 samples) | 146 / 119 / 107 | 97 / 61 / 81 |
| runs with a landed edit | 34 / 27 / 27 | 25 / 27 / 27 |

The adapter writes ~20% more per step (longer thinking), takes ~20% longer per call, makes fewer edits, and
therefore times out without a patch more often. Discordant wins concentrate on tasks the untrained agent
solves reliably (`fastapi_14360` 3×, `fastapi_15589`, `fastapi_5624`, `fastapi_9425`, `fastapi_9753` 2× each):
the adapter lost easy tasks to the clock. Adapter-only wins: 5 (`fastapi_14616`, `fastapi_14873`,
`fastapi_15589`, `fastapi_9425`, `rich_3063`).

Likely causes: the training set is dominated by long, thorough successful trajectories (median 17 tool
calls, 15K tokens, 36% supervised tokens of which most are thinking text), so SFT taught verbosity and
deliberation that the budget punishes; 2 epochs at lr 1e-4 on 90 examples is also a large behavioral shift
for 245M trainable parameters.

## What to try in v2 (not run)

1. **Mask the thinking channel out of the loss** (train on tool calls / final text only) so the agent keeps
   its native brevity while learning the action policy.
2. **Efficiency-weighted data**: the strict filter (≤14 calls, ≤12K tokens) leaves only 15 examples / 8
   tasks, so instead weight examples by 1/length or cap thinking tokens per step during rendering.
3. Smaller shift: 1 epoch, lr 5e-5, or rank 16; or merge only attention projections.
4. More and faster successes: harvest 12 samples per task on the 57 training tasks with a shorter time
   budget (6 min) so only efficient trajectories survive (~20 GPU-h).
5. Evaluate every variant on the same 38 held-out tasks × 3 samples with this paired protocol.

## Artifacts

`out_gates/s0/G1_lora/` (G1), `out_gates/s{1,2,3}/{T1_toolfix,G1_lora}/` (screen; job_summary, patches,
test logs, traces), `gates.log`, `gates_analysis.json`, `serve_gates.log`, vLLM logs. Adapters:
`../adapter_h1_final/` (fp32 PEFT), `../adapter_h1_packaged/` (bf16, competition config); weights are
outside git (also on snapshot `gemma-train-20261015-envsnap`). Submission candidate built but not uploaded:
`submission_build/lora_h1_20261016/` (zip sha 612929d5…).

## Infrastructure

Trained self-hosted on a Spot a2-highgpu-4g (4× A100-40GB) from the harvest environment snapshot after four
Fireworks managed-SFT attempts failed (`reasoning`/`arguments` format and platform issues; see HANDOFF).
Training ≈ 5.5 h wall including one preemption + resume; gates ≈ 1.7 h. VM and disk deleted 16:11 UTC;
snapshots kept: `gemma-harvest-20261015-envsnap` (eval env), `gemma-train-20261015-envsnap` (eval + training
env + bf16 weights + adapter, 156 GB), `gemma-harvest-20261015-snap` (base).
