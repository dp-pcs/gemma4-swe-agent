#!/usr/bin/env bash
# On the training/eval VM, after train_lora.py has saved ~/train/adapter_h1:
#   run_gates.sh [ADAPTER_DIR]    # default ~/train/adapter_h1 (use .../epoch0 to test the first epoch)
# 1) package the adapter (bf16, competition config)   -> ~/matrix/adapters/swe_rft_h1
# 2) build the G1_lora arm (T1 prompt tree + adapter) -> ~/matrix/arms/G1_lora
# 3) start four vLLM replicas with the LoRA module
# 4) G1: 12 smoke tasks, adapter arm only            -> ~/matrix/out_gates/s0/G1_lora
# 5) G2/G3: 38 held-out tasks x 3 samples, T1_toolfix vs G1_lora (same out dir, rounds s1..s3)
# Markers: GATES_SERVE_OK, GATES_G1_DONE, GATES_SCREEN_DONE in ~/matrix/gates.log
set -euo pipefail
A=${1:-$HOME/train/adapter_h1}
M=$HOME/matrix
D=$HOME/competition/competition_data
LOG=$M/gates.log
exec > >(tee -a "$LOG") 2>&1
echo "=== run_gates $(date -u +%FT%TZ) adapter=$A ==="

pkill -f "[t]rain_lora.py" 2>/dev/null || true
sleep 3
rm -rf "$M/adapters/swe_rft_h1" "$M/arms/G1_lora"
"$HOME/train/.venv/bin/python" -I "$HOME/train/package_adapter.py" "$A" "$M/adapters/swe_rft_h1"
python3 -I "$M/make_lora_arm.py" "$M/arms/T1_toolfix" "$M/adapters/swe_rft_h1" "$M/arms/G1_lora" --name swe_rft_h1
find "$M/arms" -name '._*' -delete

pkill -f "vllm.entrypoints" 2>/dev/null || true
sleep 5
export LORA_MODULES="swe_rft_h1=$M/arms/G1_lora/adapters/swe_rft_h1"
mkdir -p "$M/logs"
nohup bash "$M/serve.sh" > "$M/serve_gates.log" 2>&1 &
for i in 0 1 2 3; do
  until curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null; do sleep 15; done
done
curl -s http://127.0.0.1:8000/v1/models | grep -o '"id":"[^"]*"' | tr '\n' ' '; echo
echo GATES_SERVE_OK

source "$M/.venv/bin/activate"
EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
OUT=${GATES_OUT:-$M/out_gates}
python "$M/run_matrix.py" --arms G1_lora="$M/arms/G1_lora" --task-file "$M/g1_tasks.txt" --samples 1 \
  --endpoints "$EP" --workers-per-endpoint 3 --data-root "$D" --image swegemma-framework:matrix --out "$OUT" --seed 0
echo "G1 resolved: $(grep -l '"resolved": true' "$OUT"/s0/G1_lora/*/job_summary.json 2>/dev/null | wc -l)/12"
echo GATES_G1_DONE

python "$M/run_matrix.py" --arms T1_toolfix="$M/arms/T1_toolfix" G1_lora="$M/arms/G1_lora" \
  --task-file "$M/heldout_tasks.txt" --first-sample 1 --samples 3 \
  --endpoints "$EP" --workers-per-endpoint 5 --data-root "$D" --image swegemma-framework:matrix --out "$OUT" --seed 0
python "$M/analyze.py" "$OUT" --baseline T1_toolfix --json "$M/gates_analysis.json" || true
echo GATES_SCREEN_DONE
