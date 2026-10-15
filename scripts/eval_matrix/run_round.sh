#!/usr/bin/env bash
# Launch (or resume) one extra sample round on the matrix VM.
#   run_round.sh N ARM [ARM ...]      # e.g. run_round.sh 2 V2_budgetaware T1_toolfix
# Interrupted jobs of round N (claim without job_summary.json) are removed first, so a
# relaunch after a preemption re-runs only those. Appends MATRIX_DONE_sN to matrix_sN.log.
set -euo pipefail
N=$1; shift
M=$HOME/matrix
D=$HOME/competition/competition_data
source "$M/.venv/bin/activate"
EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
ARMS=""
for a in "$@"; do ARMS="$ARMS $a=$M/arms/$a"; done
n=0
for c in $(find "$M/out/s$N" -name claim 2>/dev/null); do
  d=$(dirname "$c")
  if [ ! -f "$d/job_summary.json" ]; then rm -rf "$d"; n=$((n+1)); fi
done
echo "round s$N: removed $n interrupted job dirs; arms:$ARMS"
nohup bash -c "python $M/run_matrix.py --arms $ARMS --first-sample $N --samples 1 \
  --task-file $M/tasks_95.txt --endpoints $EP --workers-per-endpoint 5 --data-root $D \
  --image swegemma-framework:matrix --out $M/out --seed 0 >> $M/matrix_s$N.log 2>&1; \
  echo MATRIX_DONE_s$N >> $M/matrix_s$N.log" > /dev/null 2>&1 &
echo "round s$N launched: $(date -u +%FT%TZ)"
