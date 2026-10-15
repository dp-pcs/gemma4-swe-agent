# Scorer-parity screen: public v2/v3 recipes and the T1 tool-reliability arm — 2026-10-15

## Final result (three samples of V2 and T1, one of A and V3; 760 runs)

| Arm | Samples | Resolved | Rate | Per sample | Paired vs V2 (W/L, net, sign-test p) |
| --- | :---: | ---: | ---: | :---: | :---: |
| T1_toolfix | 3 | 112/285 | 39.3% | 36, 40, 36 | 18/13, +5, **p = 0.47** |
| V2_budgetaware (baseline; Kaggle ref 57214360, pending) | 3 | 107/285 | 37.5% | 37, 31, 39 | — |
| V3_honghanhhh | 1 | 38/95 | 40.0% | 38 | 6/5, +1, p = 1.0 |
| A_recipe (Kaggle 0.15 = 9/58) | 1 (+1 on 10-14) | 35/95 | 36.8% | 35 (37 on 10-14) | 5/7, −2, p = 0.77 |

**T1 is not promoted.** The +8 it showed after two samples came from V2's low draw in s1
(11W/2L); s2 went 3W/6L the other way. The identical V2 configuration scored 37, 31 and 39 on
three passes, so the local one-sample standard deviation is about 3 tasks, and every
prompt/tool configuration tested here sits in one 36–40% band. T1's mechanics are confirmed
(malformed `edit_file` 29% → 6%, timeouts 64 → 51 of 285) but it trades timeouts for empty
patches (32 → 41), and the wrong-patch count is identical (81 vs 81). It remains the right
*harvest* configuration for T3 because its trajectories are clean, and it is never worse than
V2 — but it earns no submission on this evidence.

Implication for the plan: the prompt/tool lever is exhausted at ~38/95 locally; 18/58 on
Kaggle needs ~55–60/95. Proceed to T3 (rejection-sampling SFT) with T1's protocol as the
harvest agent; keep V2 as the submission base until the Kaggle anchor score arrives.

---

The interim notes below were written after s0 and s1 and are kept for the record.

## Question

Ref 57163806 (`A_recipe`, the superseded honghanhhh prompt) scored 0.15 = 9/58 on Kaggle while
the 19-team 0.22 cluster runs flexonafft's `budget-aware v2`. This run (1) re-anchors on v2 and
honghanhhh's current v3 (v2 + three prompt edits), (2) gives a second local sample of `A_recipe`
to calibrate the local↔public exchange rate, and (3) tests **T1**, the tool-reliability package
built from the 2026-10-14 trace analysis (`submission_build/t1_toolfix_20261015/`): five tools
(no `write_file`, no graph tools), `edit_file` only for ≤3-line colon-free targets with a
heredoc Python edit as the primary path otherwise, first edit by call 8, one free `get_status`,
small tool outputs. T1 is V3 plus that package; nothing else differs.

## Result after two samples

| Arm | Samples | Resolved | Rate | Paired vs V2 (W/L, net, sign-test p) |
| --- | :---: | ---: | ---: | :---: |
| **T1_toolfix** | 2 | **76/190** | **40.0%** | **15/7, +8, p = 0.13** |
| V2_budgetaware (baseline; Kaggle ref 57214360, pending) | 2 | 68/190 | 35.8% | — |
| V3_honghanhhh | 1 | 38/95 | 40.0% | 6/5, +1, p = 1.0 |
| A_recipe (Kaggle 0.15 = 9/58) | 1 (+1 on 10-14) | 35/95 (37 on 10-14) | 36.8% | 5/7, −2, p = 0.77 |

Per sample: T1 36 → 40, V2 37 → 31 (10 of 95 baseline tasks flipped between identical reruns).
T1 vs V2 by round: s0 4W/5L, s1 11W/2L. T1 clears the pre-registered magnitude gate (net ≥ +4)
but not the significance gate (p < 0.1); **s2 decides promotion.**

Failure mix (190 runs each): T1 wrong patch 56, timeout 36, empty 22; V2 wrong patch 54,
timeout 46, empty 21. T1's budget discipline removed ten timeouts; the wrong-patch bucket —
comprehension — is unchanged, as predicted on 10-14.

Across all 570 runs, 50 of 95 tasks were solved by at least one run and 45 by none.

## Mechanism check (what T1 actually changed)

| Arm (s0) | `edit_file` calls | malformed | `write_file` (rejected) | heredoc edits | runs with a landed edit | median first edit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A_recipe | 325 | 41% | 63 (47) | 0 | 79/95 | call 13 |
| V2 | 250 | 21% | 27 (0) | 0 | 67/95 | call 14 |
| V3 | 217 | 22% | 24 (17) | 1 | 72/95 | call 16 |
| T1 | 21 | 10% | 0 | 331 | 81/95 | call 11 |

s1: V2 malformed 27% (65/244), 25 edits after budget, 63/95 landed; T1 malformed 0% (0/25), 335
heredoc edits, 80/95 landed, first edit at call 12. The package works mechanically; its score
effect is modest because most failures are wrong patches, not lost edits.

## Exchange rate

`A_recipe` is 36/95 locally (two-sample mean) and 9/58 publicly (15.5%); V2 is 34/95 locally
with its Kaggle score pending. The hidden repositories are private and unrelated to the four
public ones, so the local set is a relative instrument. On this evidence 18/58 (0.30) needs the
local rate near 55–60%, which no prompt/tool configuration has approached; the remaining lever is
training (T3), and T1's trajectories are the right harvest configuration because almost none of
its tool calls are malformed (`scripts/rft/build_sft_jsonl.py` dry run on the 10-14 corpus kept
only 49 of 149 resolved runs, 92 dropped for malformed tool results).

## Setup

Same as 2026-10-14 (`results/eval_matrix_20261014/RESULTS.md`): 95 gold-verified FastAPI/Rich
tasks (`tasks_95.txt`), organizer Evaluator with 32K context, `EventsCompactionConfig(15, 2,
14336, 5)`, `ContextCacheConfig(2048, 1800, 10)`, grading image `04716dc0…`, four vLLM 0.19.1
replicas TP=1 on A100-40GB (KV cache 18,320 tokens each), 5 concurrent agents per replica,
jobs shuffled within a sample round. Arms are the exact trees in `arms/`. Runner:
`scripts/eval_matrix/` (`remote_bootstrap.sh setup|serve|matrix|resume`, `spot_watchdog.sh`,
`mechanism_check.py`).

## Infrastructure chronology

- 03:17–04:40 UTC: a `gcloud compute disks snapshot --async` call with a bad flag printed only
  the snapshot name and created nothing; re-issued as `snapshots create`.
- 04:43: Spot a2-highgpu-4g in us-central1-c; environment built from the serving lock (14, then
  16, official-wheelhouse wheels; the organizer `vllm==0.19.1` and `safetensors==0.8.0` builds
  are not on PyPI and came from `results/consumer_verification_20261013/deployment.tar`).
- Two launch bugs, each failing every job in seconds: the bundled `swegemma-0.2.11` wheel was the
  pre-2026-10-12 build (sha `63f054a3…`, no `verification_timeout_seconds`); macOS AppleDouble
  `._*` files in the arm trees were rejected by `adk_submission`.
- Preempted 05:04 and 05:21 in us-central1-c; on-demand stocked out in nine zones; Spot found in
  us-central1-a at 06:04 from an incremental snapshot of the built disk. Clean start 06:09.
- Preempted 07:34; restarted 13:15 by the watchdog (idle gap, no GPU billing while stopped);
  s0 complete 14:01, s1 complete 15:06, s2 launched 15:06 and complete 16:07. A gcloud token
  expiry at 14:54 needed an interactive `gcloud auth login` before collection. All matrix
  resources deleted 16:12 and verified absent; ≈6 Spot VM-hours (≈24 GPU-h) in total.

## Artifacts

`out/s{0,1,2}/<arm>/<task>/` (job_summary.json, agent.patch, test_output.log, traces/),
`analysis.json`/`analysis.txt` (analyze.py, baseline V2), `mechanism_s0.txt`, `mechanism_s1.txt`,
`matrix_s*.log`, `serve.log`, `setup.log`, `logs/`, `gpu_matrix_{start,end}_utc.txt`, `arms/`,
`tasks_95.txt`, `serving_requirements.lock`.
