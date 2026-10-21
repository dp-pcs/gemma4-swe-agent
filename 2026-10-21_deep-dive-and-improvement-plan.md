# Gemma 4 SWE Agent — Deep Dive & Improvement Plan (2026-10-21)

Inputs: the Oct 21 rundown, HANDOFF.md (Oct 13–21), the harness README, the T3_7m prompt tree, and a fresh analysis of the 684 runs in `results/harvest2_20261019/gates_v4/out_gates_v4` (6 prompt arms × 38 held-out tasks × 3 samples).

---

## 1. Diagnosis — what we are doing wrong

### 1.1 We are steering by noise
- **Public LB has been flat since Oct 7.** Real submissions scored 7, 4, 7, 9, 7, 10, 8 of 58 → mean **7.4/58 (12.8%)**. At that rate the *binomial* SD of a single 58-task draw is **±2.5 tasks**. All seven scores are consistent with one unchanged true rate. No change in two weeks — including T1's "best" 0.17 — has a demonstrated public effect.
- **Finding 04 (T3 local win, public loss) is not an open question.** 10 vs 8 has an SD of ~3.6 tasks on the difference. One submission per config cannot detect anything smaller than ~±5 tasks.
- **Local screens have a winner's-curse problem.** Six-plus prompt arms were screened on the same 38 tasks; picking the max of noisy arms inflates its apparent gain. T3's edge (+7 net vs T1@8, p≈0.12–0.14) is plausibly real but small: ≈ +2 tasks/38 locally → ≈ +1 task/58 publicly after the 0.35–0.45 exchange rate. Below public noise by construction.
- **The leaders' 14/58 is also a max of noisy draws.** A team with a true ~18% rate (10.4/58 expected) hits ≥14 in a single draw ~10% of the time, and near-certainly across ~20 submissions. The true gap to the top is likely +3–4 tasks, not +6–7. Private LB will deflate lucky public scores.

### 1.2 The proxy is the wrong distribution
- The 38-task held-out screen is **23 FastAPI + 15 Rich only** — no requests/httpx, and nothing the model hasn't memorised. Public and private tasks come from unseen repos.
- Exchange rate public ≈ 0.35–0.45 × local. Rules tuned on FastAPI/Rich (e.g. the `docs_src/` instruction) may not transfer.
- Per curation notes, hidden tasks were filtered by whether a larger frontier model could pass (or nearly pass) them — they are solvable, but by a much stronger model on unfamiliar code.

### 1.3 We are tuning knobs that only move the coin-flip tasks
- T3_7m per-task outcomes over 3 samples: **22/38 never solved, 10/38 always solved**, 6 in between.
- **Union of all 684 runs across all six arms = 19/38.** Prompt wording only redistributes the ~6 coin-flip tasks. That is why every prompt arm sits in one band (29–35%).

### 1.4 Mechanisms we think are working are not firing
- **`get_status` was called 5 times in 114 T3_7m runs.** The call-5 triage checkpoint — the core of T3's design — almost never triggers as written. Whatever T3 gained came from other wording (or noise).
- `edit_file` was used 10 times in 114 runs; the heredoc protocol replaced it entirely (fine, but heredoc edits cost ~2× the tokens of old/new text).
- The prompt calls `get_status` "free" — it is free in the call budget but still costs a full model turn (10–20 s of decode).

### 1.5 The clock is spent thinking, and timeouts are pure zeros
- **Wall time ≈ 0.038 s × completion tokens (r = 0.89 over 684 runs)** → ~26 tok/s; tools are negligible.
- ~80% of output is thinking/visible text (2.27M chars) vs tool arguments (0.55M chars) in T3_7m.
- **11% of steps (>2K chars) carry 62% of all thinking**; 4% of steps (>4K chars) carry 41%. Some steps run to the 4,096-token thinking cap.
- **0 of 233 timed-out runs resolved across all six arms**, even the ~35% with a non-empty patch. The long-think tail converts directly into zeros. Hidden-repo runs are very likely longer (the v3 adapter at 8 min blew the 12 h ceiling), so this bucket is bigger on the real target.

### 1.6 We use one decode stream on hardware built for many
- The scorer runs tasks **sequentially**; within a task the agent makes one LLM call at a time. On 4×L4 with a 4-bit 31B model, decode is memory-bandwidth-bound — batch 3–4 costs little extra latency per stream. Most of the available tokens/second is idle.
- **ParallelAgent / multi-agent pipelines have never been tried.** They are supported: `adk_submission/compiler.py` compiles `ParallelAgent` and `SequentialAgent`; ADK gives each parallel sub-agent an isolated branch; `max_tool_calls` / `max_turns` / `max_time_minutes` are participant-set in `eval_config.yaml`.

### 1.7 What we got right
- Closing the LoRA SFT line (4 adapters, best neutral; ~120 trajectories from 2 repos cannot teach transfer).
- The 6–7 min cap for scorer safety; paired screens; the localization oracle (gold-file edited in only 56–64% of runs, 0% resolve otherwise).
- Snapshots carry full git history (checked: rich snapshot has 3,864 commits), so history-based localization *does* transfer to hidden repos.

### 1.8 Loose end
- The rundown lists **T5_locate_7m at 33.3%**, but HANDOFF says T5 never started (Spot stockout) and no T5 outputs are in the repo. Reconcile before relying on that number.

---

## 2. Ideas, ranked by expected public impact ÷ cost

### A. Parallel best-of-3 solvers + selector — biggest lever (new)
**Design (all declarative, no harness changes):**
```
root: SequentialAgent
  1. locate      (LlmAgent, ≤3 calls) — run SHELL_LOCATE shortlist + repro once, write /tmp/ctx.md
  2. solvers     (ParallelAgent)
       solver_a | solver_b | solver_c   (temp ~0.7, each in its own git worktree)
         - setup: echo '.wt/' >> .git/info/exclude; git worktree add .wt/<x> HEAD
         - edit/test only inside .wt/<x> (read_file/edit_file accept .wt/<x>/... paths)
         - verify with PYTHONPATH=$PWD(:$PWD/src) inside the worktree
         - stop by ~4:30 elapsed; write /tmp/cand_<x>.diff + /tmp/cand_<x>.json (repro/test pass flags)
         - NO submit_patch tool
  3. selector    (LlmAgent) — rank: verified > agreement (identical/overlapping diffs) > smallest;
                  git apply into /workspace; rm -rf .wt; git worktree prune; git status; submit_patch
eval_config: max_tool_calls ~120, max_turns ~250, max_time_minutes 6.5
```
**Evidence:** temperature 0.7 does not hurt pass@1 (harvest 1: 38.2% at 0.7 vs T1 39.3% at 0.2) but adds diversity (48/95 tasks solved at least once in 6 samples). On the 38×3 data, pass@3 is 16–17/38 vs pass@1 13.3, and a naive vote (identical normalized diff, else modal file-set, else smallest patch) already recovers **15–17/38**.
**Expected:** +3 tasks/38 locally (~+8 pp), more with temp-0.7 diversity; publicly maybe +1.5–3 tasks. Also turns some timeouts into submitted patches (three shots finish before one long one).
**Unknowns to kill first:** (1) per-stream decode slowdown at concurrency 3 on 4×L4; (2) import path inside worktrees on src-layout repos; (3) harness nudge after the root finishes without submit re-running the whole pipeline — selector must apply a patch *first*, then deliberate; (4) the local rig must emulate L4 batch latency or the screen is fiction.

### B. Thinking discipline — cheap, compounds with A
- One-variable screen: `thinking_budget` 4096 → **1536** (and 1024). The cap only bites the long tail that eats ~half the clock. Prior 2048 test: neutral score, fewer timeouts. Under parallelism, speed is worth more.
- Prompt: "think in ≤5 sentences before each call; long reasoning only before the first edit."

### C. Localization for unfamiliar repos
- Put SHELL_LOCATE (87–94% oracle top-5/10 recall, history-based, transfers) into the shared `locate` stage so all solvers inherit it.
- Diversify solvers by strategy: A follows the traceback/repro, B the shortlist, C the code-graph tools (`search_similar_code`, `get_code_neighbors`). Graph tools were dismissed on repos the model already knows; they may matter on unseen ones. Test on the unfamiliar-repo proxy (D).

### D. Fix the proxy
1. Add the 13 requests + 1 httpx tasks (needs the second sandbox image).
2. Build **40–60 tasks from 10–15 less-known Python repos** (SWE-rebench / SWE-Gym style: snapshot + test_patch + deps baked into the sandbox image). This is the closest thing we can get to "repos we've never seen".
3. Re-rank T1, T3_7m and the new arms there. Prefer configs that win on *both* proxies.

### E. Submission discipline
- Pool public scores by config family; treat any single score as ±2.5 tasks.
- Spend slots only on candidates with an expected effect of ≥ +3 public tasks, and **replicate** them (3 submissions → SD ≈ ±1.5).
- Final two picks: best-evidence config + a structurally different hedge.

### F. Paper track (Nov 12 deadline, separate $35K pool)
- We already have publishable material: the noise/lattice analysis, four LoRA negative results with mechanisms, the localization oracle, token-economics of the time budget, and (if it lands) parallel best-of-N under a sequential harness.

### Stop doing
- More single-agent prompt wording arms on FastAPI/Rich; sampling-knob sweeps; LoRA SFT on the current data.

---

## 3. Plan (Oct 21 → Dec 2)

### Week 1 — Oct 21–27: de-risk parallelism
| Step | What | Gate |
|---|---|---|
| 1 | **L4 throughput benchmark** in a Kaggle 4×L4 notebook (scorer hardware) or a GCP g2-standard-48: exact vLLM config (TP=4, gemma4 parsers, 32K, `gpu_memory_utilization` 0.80), ~10K-token prompts, concurrency 1/2/3/4; check prefix caching. | Per-stream decode at concurrency 3 ≥ 75% of single-stream → go. |
| 2 | Calibrate the local rig to those numbers (workers per endpoint / latency scaling) so parallel arms are timed honestly. | Single-stream T3_7m mean time reproduces ~350 s. |
| 3 | Build arm **P3** (design A) and a mechanics smoke on 5 tasks: patch lands in /workspace, `.wt/` never in the diff, no pipeline re-run on nudge, worst-case wall ≤ 6.5 min. | 5/5 mechanically clean. |
| 4 | Screen P3 vs T3_7m, 38×1 then 38×3 (paired). | Net ≥ +6 over 114 pairs → candidate. |
| — | Kaggle slots: submit T3_7m (the planned, scorer-safe config) to add a baseline point; otherwise hold. | — |

### Week 2 — Oct 28–Nov 3: proxy + first public replicate
- Build the unfamiliar-repo proxy (D) and add requests/httpx. Re-run T1, T3_7m, P3.
- If P3 passes both proxies: submit it **3 times** this week; compare the pooled mean against the 7.4/58 baseline pool.
- Screen thinking budget 1536 inside P3.

### Week 3 — Nov 4–10: tune the parallel design
- N = 2 vs 3 vs 4; solver strategy diversification (C); selector rules; graph tools on the unfamiliar proxy.
- Decide on the paper track by Nov 5; draft by Nov 12 if yes.

### Weeks 4–5 — Nov 11–24: harden
- Runtime safety at the 12 h ceiling (one source says setup time counts toward it; keep margin), odd repo layouts, worktree failure fallbacks (solver falls back to direct /workspace edit if worktree setup fails).
- Replicate submissions of the leading config. Team-merge deadline Nov 25 — consider whether to merge.

### Week 6 — Nov 25–Dec 2: freeze
- Final two: leading P-config + T3_7m (or T1_6m) as the hedge.

### Budget
Each 38×3 screen ≈ 1.2 h on Spot a2-highgpu-4g (≈ $5–8). Proxy build is mostly CPU + engineering. L4 benchmark ≈ 1 h on Kaggle quota or ≈ $5 on GCP.
