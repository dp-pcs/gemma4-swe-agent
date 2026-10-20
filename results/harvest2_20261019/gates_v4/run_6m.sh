#!/usr/bin/env bash
# Budget test: T1 @ 6 min and v4 adapter @ 6 min on the 38 held-out tasks x 3, into out_gates_v4 (pairs with the T1_toolfix 8-min runs there).
set -uo pipefail
M=$HOME/matrix; D=$HOME/competition/competition_data; OUT=$M/out_gates_v4
exec >> $M/gates.log 2>&1
echo "=== run_6m $(date -u +%FT%TZ) arms=T1_6m,G1_lora_6m ==="
source $M/.venv/bin/activate
EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
for i in 0 1 2 3; do curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null || echo "SERVER_DOWN $i"; done
python $M/run_matrix.py --arms T1_6m=$M/arms/T1_6m G1_lora_6m=$M/arms/G1_lora_6m --task-file $M/heldout_tasks.txt --first-sample 1 --samples 3 \
  --endpoints "$EP" --workers-per-endpoint 5 --data-root $D --image swegemma-framework:matrix --out $OUT --seed 0
python $M/analyze.py $OUT --baseline T1_toolfix --json $M/gates_analysis_6m.json || true
echo GATES_6M_DONE
