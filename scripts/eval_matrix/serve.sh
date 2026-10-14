#!/usr/bin/env bash
# Start one vLLM replica per GPU at the scorer's 32K context.
# Flags follow adk_submission.VllmServer (gemma4 parsers, reasoning channel config,
# enable_thinking, no full-ISL reservation); TP=1 per local A100 instead of TP=4 on L4.
set -euo pipefail
M=$HOME/matrix
source "$M/.venv/bin/activate"
export VLLM_NO_USAGE_STATS=1 VLLM_SERVER_DEV_MODE=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
N=$(nvidia-smi -L | wc -l)
mkdir -p "$M/logs"
for i in $(seq 0 $((N - 1))); do
  CUDA_VISIBLE_DEVICES=$i nohup python -m vllm.entrypoints.openai.api_server \
    --model "$HOME/competition/model" --served-model-name gemma-4-31b-it-qat-w4a16-ct \
    --host 127.0.0.1 --port $((8000 + i)) \
    --max-model-len 32768 --dtype auto --gpu-memory-utilization 0.93 --kv-cache-dtype ${KV_DTYPE:-auto} \
    --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 \
    --reasoning-config '{"reasoning_start_str":"<|channel>","reasoning_end_str":"<channel|>"}' \
    --default-chat-template-kwargs '{"enable_thinking":true}' \
    --no-scheduler-reserve-full-isl \
    --language-model-only --skip-mm-profiling \
    --max-num-seqs 8 --max-num-batched-tokens 8192 --cudagraph-capture-sizes 1 2 4 8 \
    > "$M/logs/vllm_$i.log" 2>&1 &
done
for i in $(seq 0 $((N - 1))); do
  until curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null; do sleep 10; done
  echo "replica $i ready"
done
grep -h "KV cache" "$M"/logs/vllm_*.log | head -n "$N" || true
