"""Go/no-go for Design A: recompute pass@1, pass@3, naive-vote under a 6K completion-token truncation,
simulating the per-solver budget available at a 5-min cap (per the other agent's math)."""
import json, pathlib, random
from collections import defaultdict

BASE = pathlib.Path('results/harvest2_20261019/gates_v4/out_gates_v4')
ARMS = ['T1_toolfix', 'T1_6m', 'T2_verify_6m', 'T3_dynamic_8m', 'T3_7m', 'T3_bail3']
TRUNC_TOKENS = 6000

# Load all runs: task -> arm -> sample -> {resolved, completion_tokens, submitted}
runs = defaultdict(lambda: defaultdict(dict))
for s_dir in sorted(BASE.glob('s*')):
    s = s_dir.name
    for arm_dir in s_dir.iterdir():
        if arm_dir.name not in ARMS: continue
        for task_dir in arm_dir.iterdir():
            jf = task_dir / 'job_summary.json'
            if not jf.exists(): continue
            data = json.loads(jf.read_text())
            trace_path = task_dir / 'traces' / f'trace_{task_dir.name}.json'
            completion_tokens = None
            if trace_path.exists():
                try:
                    trace = json.loads(trace_path.read_text())
                    completion_tokens = trace.get('final_metrics', {}).get('total_completion_tokens')
                except Exception:
                    pass
            runs[task_dir.name][(arm_dir.name, s)] = {
                'resolved': data.get('resolved', False),
                'completion_tokens': completion_tokens,
                'patch_bytes': data.get('patch_bytes', 0),
            }

all_tasks = sorted(runs.keys())
print(f'Total tasks: {len(all_tasks)}')

def resolved_under_truncation(rec, trunc):
    if not rec['resolved']:
        return False
    ct = rec['completion_tokens']
    if ct is None:
        return rec['resolved']  # can't truncate, assume it holds (conservative toward Design A)
    return ct <= trunc

# Pass@1: use T3_7m s1 only as the reference "single solver" arm
pass1_raw = sum(1 for t in all_tasks if ('T3_7m', 's1') in runs[t] and runs[t][('T3_7m','s1')]['resolved'])
pass1_trunc = sum(1 for t in all_tasks if ('T3_7m', 's1') in runs[t] and resolved_under_truncation(runs[t][('T3_7m','s1')], TRUNC_TOKENS))
print(f'\nPass@1 (T3_7m s1): raw={pass1_raw}/{len(all_tasks)}, truncated@{TRUNC_TOKENS}={pass1_trunc}/{len(all_tasks)}')

# Pass@3: use T3_7m's 3 samples as a proxy for "3 independent solver attempts"
pass3_raw = 0
pass3_trunc = 0
vote_raw = 0
vote_trunc = 0
for t in all_tasks:
    samples = [runs[t].get(('T3_7m', s)) for s in ['s1','s2','s3']]
    samples = [s for s in samples if s is not None]
    if not samples: continue
    # pass@3: resolved if ANY of 3 resolved (oracle selection)
    if any(s['resolved'] for s in samples):
        pass3_raw += 1
    if any(resolved_under_truncation(s, TRUNC_TOKENS) for s in samples):
        pass3_trunc += 1
    # naive vote: smallest patch among those with patch_bytes>0 (proxy for the "verified>agreement>smallest" rule
    # without diff data; smallest is the only signal available in job_summary)
    candidates = [s for s in samples if s['patch_bytes'] > 0]
    if candidates:
        picked = min(candidates, key=lambda s: s['patch_bytes'])
        if picked['resolved']:
            vote_raw += 1
        cand_t = [s for s in samples if s['patch_bytes'] > 0 and (s['completion_tokens'] is None or s['completion_tokens'] <= TRUNC_TOKENS)]
        if cand_t:
            picked_t = min(cand_t, key=lambda s: s['patch_bytes'])
            if picked_t['resolved'] and (picked_t['completion_tokens'] is None or picked_t['completion_tokens'] <= TRUNC_TOKENS):
                vote_trunc += 1

n = len(all_tasks)
print(f'Pass@3 (oracle, any of 3 T3_7m samples resolved): raw={pass3_raw}/{n}, truncated@{TRUNC_TOKENS}={pass3_trunc}/{n}')
print(f'Naive vote (smallest non-empty patch among 3): raw={vote_raw}/{n}, truncated@{TRUNC_TOKENS}={vote_trunc}/{n}')

# Token distribution context
all_ct = [r['completion_tokens'] for t in all_tasks for r in runs[t].values() if r['completion_tokens'] is not None]
all_ct.sort()
if all_ct:
    import statistics
    print(f'\nCompletion-token distribution across all runs/arms (n={len(all_ct)}):')
    print(f'  median={statistics.median(all_ct):.0f}, p75={all_ct[int(len(all_ct)*0.75)]:.0f}, p90={all_ct[int(len(all_ct)*0.90)]:.0f}, max={max(all_ct)}')
    over_trunc = sum(1 for c in all_ct if c > TRUNC_TOKENS)
    print(f'  runs exceeding {TRUNC_TOKENS} tokens: {over_trunc}/{len(all_ct)} ({100*over_trunc/len(all_ct):.1f}%)')
