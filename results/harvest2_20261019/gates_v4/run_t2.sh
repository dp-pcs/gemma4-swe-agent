#!/usr/bin/env bash
# T2 verify-before-submit prompt (6-min budget) on the 38 held-out tasks x 3, into out_gates_v4; paired vs T1_6m and vs T1_toolfix (8 min).
set -uo pipefail
M=$HOME/matrix; D=$HOME/competition/competition_data; OUT=$M/out_gates_v4
exec >> $M/gates.log 2>&1
echo "=== run_t2 $(date -u +%FT%TZ) arm=T2_verify_6m ==="
source $M/.venv/bin/activate
EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
for i in 0 1 2 3; do curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null || echo "SERVER_DOWN $i"; done
python $M/run_matrix.py --arms T2_verify_6m=$M/arms/T2_verify_6m --task-file $M/heldout_tasks.txt --first-sample 1 --samples 3 \
  --endpoints "$EP" --workers-per-endpoint 5 --data-root $D --image swegemma-framework:matrix --out $OUT --seed 0
python $M/analyze.py $OUT --baseline T1_6m --json $M/gates_analysis_t2_vs_t1_6m.json || true
python $M/analyze.py $OUT --baseline T1_toolfix --json $M/gates_analysis_t2_vs_t1_8m.json || true
echo GATES_T2_DONE
