#!/usr/bin/env bash
# Runs on the matrix VM after `matrix_bundle.tgz` is copied to $HOME.
# Phases (idempotent, resumable): extract -> split lock -> vm_setup -> serve -> matrix.
#   remote_bootstrap.sh setup      # extract bundle, build the pinned env, load sandbox image
#   remote_bootstrap.sh serve      # start 4 vLLM replicas and wait until ready
#   remote_bootstrap.sh matrix     # launch the two matrix rounds under nohup
set -euo pipefail
M=$HOME/matrix
D=$HOME/competition/competition_data
phase=${1:-setup}

case "$phase" in
  setup)
    mkdir -p "$M"
    tar -xzf "$HOME/matrix_bundle.tgz" -C "$M"
    cp "$M"/scripts/*.py "$M"/scripts/*.sh "$M"/
    chmod +x "$M"/*.sh
    if [ ! -f "$HOME/official_up/official.lock" ]; then
      python3 -I "$M/split_lock.py" "$M/serving_requirements.lock" "$D/wheels" "$HOME/official_up"
    fi
    bash "$M/vm_setup.sh" 2>&1 | tee -a "$M/setup.log"
    ;;
  serve)
    mkdir -p "$M/logs"
    nohup bash "$M/serve.sh" > "$M/serve.log" 2>&1 &
    for i in 0 1 2 3; do
      until curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null; do sleep 15; done
      echo "replica $i ready"
    done
    grep -h "GPU KV cache size" "$M"/logs/vllm_*.log | head -4 || true
    ;;
  matrix)
    source "$M/.venv/bin/activate"
    EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
    A="A_recipe=$M/arms/A_recipe V2_budgetaware=$M/arms/V2_budgetaware V3_honghanhhh=$M/arms/V3_honghanhhh T1_toolfix=$M/arms/T1_toolfix"
    COMMON="--task-file $M/tasks_95.txt --endpoints $EP --workers-per-endpoint 5 --data-root $D --image swegemma-framework:matrix --out $M/out --seed 0"
    date -u +%FT%TZ > "$M/gpu_matrix_start_utc.txt"
    nohup bash -c "python $M/run_matrix.py --arms $A --samples 1 $COMMON > $M/matrix_s0.log 2>&1 && \
      python $M/run_matrix.py --arms V2_budgetaware=$M/arms/V2_budgetaware T1_toolfix=$M/arms/T1_toolfix --first-sample 1 --samples 1 $COMMON > $M/matrix_s1.log 2>&1; \
      echo MATRIX_DONE >> $M/matrix_s1.log" > /dev/null 2>&1 &
    echo "matrix launched: $(date -u +%FT%TZ)"
    ;;
  *)
    echo "unknown phase: $phase" >&2; exit 2 ;;
esac
