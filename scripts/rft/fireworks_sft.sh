#!/usr/bin/env bash
# Fireworks managed LoRA SFT for the Gemma 4 31B agent (T3b).
#   fireworks_sft.sh upload  RUN_ID TRAIN.jsonl [EVAL.jsonl]   # create dataset(s)
#   fireworks_sft.sh train   RUN_ID [EPOCHS=2] [LORA_RANK=32] [LR]   # create the SFT job
#   fireworks_sft.sh status  RUN_ID                             # poll until done
#   fireworks_sft.sh download RUN_ID OUT_DIR                    # PEFT adapter -> OUT_DIR
# Base model: accounts/fireworks/models/gemma-4-31b-it (bf16; the competition serves the QAT
# w4a16 checkpoint, so the adapter must pass gate G1 under vLLM before anything else).
set -euo pipefail
cmd=$1; run=$2; shift 2
BASE=accounts/fireworks/models/gemma-4-31b-it
ACCOUNT=${FIREWORKS_ACCOUNT:-trilogy}
DS="swe-rft-$run"; EV="swe-rft-$run-eval"; OUT="swe-rft-$run-lora"

case "$cmd" in
  upload)
    train=$1; eval=${2:-}
    firectl dataset create "$DS" "$train" --display-name "SWE RFT $run train" --quiet
    [ -n "$eval" ] && firectl dataset create "$EV" "$eval" --display-name "SWE RFT $run eval" --quiet
    firectl dataset get "$DS" | grep -E "Name|State|Status|Example|Token"
    ;;
  train)
    epochs=${1:-2}; rank=${2:-32}; lr=${3:-}
    args=(--base-model "$BASE" --dataset "$DS" --output-model "$OUT" --display-name "swe-rft-$run"
          --epochs "$epochs" --lora-rank "$rank" --max-context-length 32768)
    [ -n "$lr" ] && args+=(--learning-rate "$lr")
    if firectl dataset get "$EV" >/dev/null 2>&1; then args+=(--evaluation-dataset "$EV"); fi
    firectl sftj create "${args[@]}" | tee "/tmp/sftj-$run.txt"
    grep -oE "accounts/[^ ]+/supervisedFineTuningJobs/[^ ]+" "/tmp/sftj-$run.txt" | head -1 > "/tmp/sftj-$run.id"
    echo "job id saved to /tmp/sftj-$run.id"
    ;;
  status)
    id=$(cat "/tmp/sftj-$run.id")
    while :; do
      st=$(firectl sftj get "$id" | grep -E "^State:" | awk '{print $2}')
      echo "$(date -u +%H:%M:%SZ) $st"
      case "$st" in COMPLETED|FAILED|CANCELLED) break;; esac
      sleep 120
    done
    firectl sftj get "$id" | grep -E "State|Model|Loss|Epoch|Error" || true
    ;;
  download)
    out=$1; mkdir -p "$out"
    firectl model download "accounts/$ACCOUNT/models/$OUT" "$out"
    ls -la "$out"; python3 -I -c "import json,sys; c=json.load(open(sys.argv[1]+'/adapter_config.json')); print({k:c[k] for k in ('r','lora_alpha','target_modules','base_model_name_or_path') if k in c})" "$out"
    ;;
  *) echo "unknown command $cmd" >&2; exit 2;;
esac
