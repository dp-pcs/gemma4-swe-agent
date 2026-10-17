# LoRA v2 (adapter_h2, thinking masked) gate results — 2026-10-17

## Verdict: not promoted (worse than v1)

| Gate | Result |
| --- | --- |
| Training | `--mask-thinking` (loss on tool calls / final text only, 10% of tokens), same 90 train / 28 eval trajectories, r=32, 2 epochs, lr 1e-4; action-only held-out loss 0.425 → 0.110 → 0.088 |
| G1 smoke (12 held-out tasks) | **3/12** (v1: 8/12); 7 runs timed out with 2–19 tool calls, 9 ended with an empty patch |
| **Held-out screen (38 × 3, paired vs T1_toolfix)** | **G1_lora 19/114 (16.7%) vs T1 41/114 (36.0%); W 1 / L 23, net −22, sign-test p ≈ 0** |

## What went wrong: repetition loops

Outside the failures the adapter is exactly what v2 aimed for — terse and fast: median 43–56 completion
tokens per model call vs 133 for the untrained agent, clean tool calls, and its resolved runs are short.
But **8 of 300 model calls in G1 (2.7%) ran to the 8192-token output cap in a repetition loop** — 5 in the
thinking channel (`Example: ... No.` repeated for 16K characters), 2 inside a tool call's arguments
(`except Exception as e:` repeated for 31K characters). Each such call costs 160–275 s of the 480 s budget,
and the call in flight at the timeout is not even counted, so the true loop rate is ≈ 5%. Result: 92 of
126 adapter runs (incl. G1) ended in `timeout` (T1: 31 of 114), mean 450 s vs 408 s per task, 18.8 vs 22.1
tool calls. Failure mix — adapter: timeout 92, empty 7, wrong 4; T1: wrong 30, timeout 31, empty 12.

Mechanism: with the thinking masked out of the loss, nothing anchors *when to stop* thinking (the
`<channel|>` token was never supervised) and 24 steps at lr 1e-4 on ≈115K action tokens (train loss
0.04–0.07) over-sharpened the action distribution; a sharpened model at temperature 0.2 falls into loops.

## Mitigation tested without retraining: `G1_lora_o2k`

Same adapter, `max_output_tokens: 2048` (T1's legitimate calls: p99 1136, max 2936 tokens; the adapter's
p99 739), so a loop costs ≤ ~45 s. Run 2026-10-17 22:02 UTC on the same 38 × 3 into `out_gates_v2`
(pairs with the T1 runs above; the T1 runs were produced under heavier server load, which slightly
favours this arm). Result: see `gates_analysis_o2k.json` / HANDOFF.

## v3 candidates (trainer options implemented, dry-run verified, not trained)

- `--max-thinking-chars 600`: truncate each `reasoning_content` before rendering so the thinking is short
  **and supervised** (median thought is 212 chars; p90 2286; max 16268) — the rendered examples shrink, so
  109 of 113 trajectories fit in 20K tokens (v1/v2: 90), median 12.8K tokens, 24% supervised; plus
  `--lr 5e-5` to reduce over-sharpening.
- `--mask-thinking --keep-thinking-markers`: v2's masking but with the `<|channel>` / `<channel|>` tokens
  supervised (the model learns to open and close thinking).
- Cheapest first check: gate `adapter_h2/epoch0` (12 steps, less sharpened) with the 2048 cap.

Artifacts: `out_gates_v2/` on the VM (`s0/G1_lora` smoke, `s{1,2,3}/{T1_toolfix,G1_lora,G1_lora_o2k}`),
`gates_analysis.json`, `gates_analysis_o2k.json`; adapters `../adapter_h2_final/` (fp32 PEFT) and
`../adapter_h2_packaged/` (bf16, as served); `adapter_h2_epoch0/`. Training ≈ 6 h wall incl. two OOM
restarts (see `scripts/rft/train_lora.py --layer-split/--offload-ckpt/--mem-probe`), gates ≈ 1.7 h.

---

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
