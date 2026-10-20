# LoRA v4 (adapter_h4, efficient-harvest data) gate results — 2026-10-20

## Verdict: neutral again (net −1) — the LoRA SFT line is closed for now

| Gate | Result |
| --- | --- |
| Data | harvest 2 (57 training tasks × 12 samples, T1 prompt @ temp 0.7, **6-min budget**): 684 runs, 267 resolved (39%), only 33 tasks ever solved; v4 set = fewest-tool-call successes from both harvests, ≤ 24 calls, 5 per task → **121 examples / 28 tasks** (median 16 calls vs 17 in v3's data) — `results/harvest2_20261019/` |
| Training | v3 recipe (`--max-thinking-chars 600 --lr 5e-5`, 2 epochs, r=32); held-out loss 1.105 → 0.321 → 0.256 (v3: 0.249 — the token metric is saturated and uninformative) |
| G1 smoke (12 held-out tasks) | **7/12** (v3 7, v1 8, v2 3); 4 timeouts, 1 wrong; median reply 112 tokens, 1 of 287 calls at the cap |
| **Held-out screen (38 × 3, paired vs T1_toolfix)** | **v4 32/114 (28.1%) vs T1 33/114 (28.9%); W 5 / L 6, net −1, p = 1.0** (incl. G1: 39/126) |

Mechanics: v4 runs longer than T1 (mean 417 s vs 398 s) with slightly fewer tool calls (21.1 vs 22.6);
failures v4: timeout 62 of 126, wrong 16, empty 9 — T1: wrong 26, timeout 36, empty 19. The efficient data
did not make the agent faster per task; it trades wrong patches for timeouts.

**Why the line is closed:** v3 and v4 are the best self-distillation can do with this harness — a 31B model
fine-tuned on 100–150 of its own successful trajectories reproduces its own behaviour (neutral), and the
adapter costs scorer time: Kaggle ref 57412209 (v3) failed with *"exceeded the allowed runtime"* under the
12-hour / ~120-sequential-task ceiling that T1 passes. An adapter would have to be *faster* than T1 per task
to be submittable at all; none of ours is.

**Follow-up running (14:05 UTC):** `run_6m.sh` — `T1_6m` and `G1_lora_6m` (`max_time_minutes: 6`) on the same
38 × 3 into `out_gates_v4`, paired against the fresh T1 @ 8 min runs: tells (a) what a scorer-safe 6-min
budget costs T1, (b) whether v4 — whose data was selected at 6 min — beats T1 under that budget.

Artifacts: `results/harvest2_20261019/gates_v4/` (runs, traces, analysis), `adapter_h4_final/` (fp32),
`adapter_h4_packaged/` (bf16 as served, sha `c98fefb2…`), candidate `submission_build/lora_h4_20261020/`
(zip sha `eccf2bc1…`, not uploaded).

---

# LoRA v3 (adapter_h3, bounded supervised thinking) gate results — 2026-10-19

## Verdict: neutral — "roughly equal" zone (user decides); first adapter that does not degrade the agent

| Gate | Result |
| --- | --- |
| Training | `--max-thinking-chars 600` (thinking kept and supervised, cut at 600 chars), `--lr 5e-5`, 2 epochs, r=32, 109 train / 35 eval trajectories (shorter examples → 109 fit vs 90); held-out loss 1.105 → 0.325 → 0.249; one Spot preemption auto-resumed |
| G1 smoke (12 held-out tasks) | **7/12** (v1 8, v2 3); 4 timeouts, 1 empty |
| **Held-out screen (38 × 3, paired vs T1_toolfix)** | **v3 31/114 (27.2%) vs T1 35/114 (30.7%); W 9 / L 13, net −4, sign-test p = 0.52** — per sample T1 12/10/13, v3 10/10/11 of 38; both resolved 22 |

## Mechanics: both earlier failure modes fixed, a residue of loops remains

| | T1_toolfix | v3 adapter |
| --- | ---: | ---: |
| completion tokens per call, median / p90 / p99 | 124 / 758 / 3340 | **109 / 623** / 4113 |
| seconds between agent steps, median | 5.5 | **4.9** |
| calls at the 8192-token cap (loops) | 0 of 2698 | **13 of 2776 (0.5%)** (v2: 2.7%) |
| mean tool calls per run | 21.8 | 22.9 |
| mean wall per run | 392 s | 409 s |
| failures: timeout / wrong / empty | 38 / 25 / 16 | **53** / 20 / 15 |

The adapter is terser and faster per step than the untrained agent (v1's verbosity is gone) and loops only
0.5% of the time (v2's 2.7% is gone), but each remaining loop still costs ~3 min, which is where the extra 15
timeouts come from. Discordant tasks: v3-only wins on `fastapi_14419` ×2, `fastapi_14873` ×2,
`fastapi_15589` ×2, `fastapi_14616`, `fastapi_9425`, `fastapi_9753`; T1-only wins on `fastapi_14458` ×3,
`fastapi_14360` ×2, `fastapi_5624` ×2 and five singles.

## Follow-ups

- `G1_lora_o4k` (same adapter, `max_output_tokens: 4096`, loops cost ≤ ~90 s): run 2026-10-19 23:12–23:54 UTC
  on the same 38 × 3 into `out_gates_v3` (pairs with the T1 runs above). **Result: 30/114 (26.3%) vs T1 35/114;
  W 4 / L 9, net −5, p = 0.27** — timeouts fell (42 vs 53) but empty patches rose (20 vs 15); the cap does not
  change the verdict. v3 ≈ T1 − 4 with or without the cap: the residual loops were not the whole gap.
- Candidate zip `submission_build/lora_h3_20261019/` (sha `488652b4…`) **uploaded 2026-10-19 23:18 UTC as Kaggle
  ref 57412209 to validate the real-adapter path → FAILED: "Your submission notebook exceeded the allowed
  runtime"** (COMPLETE, no score). The scorer runs ~120 hidden tasks sequentially under a 12-hour ceiling
  (agent-loop time only), i.e. ≲ 6 min per task on average; the adapter's longer runs plus vLLM LoRA overhead
  on 4× L4 pushed it over, while T1 (no adapter) at the same 8-min budget passed. Every adapter submission
  from here needs a 6-min (or shorter) `max_time_minutes` and must be at least as fast as T1 per task.
- Plan step 2 (if the line continues): harvest ≈ 12 samples/task on the 57 training tasks with a 6-min budget,
  keep the fastest successes, retrain with this recipe.

Artifacts: `../gates_v3/` (out_gates_v3 runs, traces, patches, logs, analyses), `../adapter_h3_final/`
(fp32), `../adapter_h3_packaged/` (bf16 as served, sha `cf2904b4…`), `adapter_h3_epoch0` on the VM disk.

---

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
favours this arm). **Result: 23/114 (20.2%) vs T1 41/114; W 0 / L 18, net −18, p ≈ 0 — still fails.**
Timeouts fell (50 vs 92 of the uncapped runs) but empty patches rose to 30 and wrong patches to 10; 4.8% of
calls still hit the (lower) cap and 10 of the first 47 runs exhausted the 28-call budget — shorter loops
turned into more loops. The v2 weights are degraded in a way no sampling config repairs; **not uploaded**
(`submission_build/lora_h2o2k_20261017/`, zip sha `dd876455…`, kept for provenance only).

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
