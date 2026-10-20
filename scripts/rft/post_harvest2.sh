#!/usr/bin/env bash
# After `HARVEST2_DONE` appears in ~/matrix/harvest2.log on the VM:
#   1) copy out_harvest2 (684 runs: 57 training tasks x 12 samples, T1 prompt @ temp 0.7, 6-min budget) to the repo
#   2) build the v4 SFT set: resolved runs from BOTH harvests, training tasks only, fewest-tool-call successes
#      first, capped per task (build_sft_jsonl.py sorts by tool calls and keeps the first PER_TASK)
#   3) with LAUNCH=1: upload the JSONL, stop the vLLM replicas and start v4 training with the v3 recipe
# Env: PER_TASK (4), MAX_CALLS (20), MAX_PROMPT (16384), LAUNCH (0), VM/ZONE/PROJECT.
set -euo pipefail
VM=${VM:-gemma-train2-20261016}; Z=${ZONE:-us-central1-f}; P=${PROJECT:-ai-coe-454404}
H1=results/harvest_20261015; H2=results/harvest2_20261019
PER_TASK=${PER_TASK:-4}; MAX_CALLS=${MAX_CALLS:-20}; MAX_PROMPT=${MAX_PROMPT:-16384}; LAUNCH=${LAUNCH:-0}
cd "$(dirname "$0")/../.."
mkdir -p "$H2"

if [ ! -d "$H2/out_harvest2" ]; then
  gcloud compute ssh "$VM" --project "$P" --zone "$Z" --quiet --command \
    'cd ~/matrix && grep -q HARVEST2_DONE harvest2.log && tar czf /tmp/out_harvest2.tgz out_harvest2 harvest2.log run_harvest2.sh && ls -la /tmp/out_harvest2.tgz | awk "{print \$5}"'
  gcloud compute scp --project "$P" --zone "$Z" --quiet "$VM:/tmp/out_harvest2.tgz" "$H2/"
  tar xzf "$H2/out_harvest2.tgz" -C "$H2"
fi
python3 -I - "$H2/out_harvest2" <<'EOF'
import json, glob, sys, collections
runs = glob.glob(sys.argv[1] + "/s*/T1_harvest/*/job_summary.json")
res = [json.load(open(p)) for p in runs]
ok = [r for r in res if r.get("resolved")]
per_task = collections.Counter(r["task_id"] for r in ok)
print(f"harvest 2: {len(res)} runs, {len(ok)} resolved ({100*len(ok)/max(len(res),1):.0f}%), "
      f"{len(per_task)} of 57 tasks solved at least once; tasks with >=4 successes: {sum(1 for v in per_task.values() if v >= 4)}")
EOF

python3 -I scripts/rft/build_sft_jsonl.py "$H1/out" "$H2/out_harvest2" --arms T1_harvest \
  --task-file "$H1/train_tasks.txt" --per-task "$PER_TASK" --max-tool-calls "$MAX_CALLS" \
  --max-prompt-tokens "$MAX_PROMPT" --out "$H2/sft_train_v4.jsonl"
python3 -I - "$H2/sft_train_v4.jsonl" <<'EOF'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
tc = sorted(sum(1 for m in r["messages"] if m["role"] == "assistant" and m.get("tool_calls")) for r in rows)
tasks = len({json.dumps(r["messages"][1]["content"])[:200] for r in rows})
print(f"sft_train_v4.jsonl: {len(rows)} examples (~{tasks} distinct tasks); tool calls per example "
      f"median {tc[len(tc)//2]} p90 {tc[int(len(tc)*.9)]} max {tc[-1]}")
EOF

if [ "$LAUNCH" = "1" ]; then
  gcloud compute scp --project "$P" --zone "$Z" --quiet "$H2/sft_train_v4.jsonl" "$VM:~/train/sft_train_v4.jsonl"
  gcloud compute ssh "$VM" --project "$P" --zone "$Z" --quiet --command 'pkill -f "vllm.entrypoints" 2>/dev/null; sleep 8; cd ~/train && mv train.log train_v3_final.log 2>/dev/null; PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True nohup .venv/bin/python -u train_lora.py --model /home/davidproctor/hf/gemma4-bf16 --train sft_train_v4.jsonl --eval sft_eval.jsonl --out /home/davidproctor/train/adapter_h4 --max-len 20480 --epochs 2 --rank 32 --lr 5e-5 --grad-accum 8 --layer-split 15,16,16,13 --head-chunk 512 --offload-ckpt --mem-probe --probe-max-gib 38 --max-thinking-chars 600 > train.log 2>&1 & sleep 15; pgrep -af "train_lora.py" | grep -v pgrep | cut -c1-80 | head -1; nvidia-smi --query-gpu=memory.used --format=csv,noheader | tr "\n" " "; echo'
  echo "v4 training launched; monitor ~/train/train.log and ~/train/adapter_h4/train_log.jsonl"
fi
