#!/usr/bin/env bash
# Harvest 2: 57 training tasks x 12 samples with the T1 prompt at temperature 0.7 and a 6-minute budget
# (time-scale 0.75), base model only (no adapter). Output ~/matrix/out_harvest2; markers in ~/matrix/harvest2.log.
set -uo pipefail
M=$HOME/matrix; D=$HOME/competition/competition_data; OUT=$M/out_harvest2
exec >> $M/harvest2.log 2>&1
echo "=== run_harvest2 $(date -u +%FT%TZ) ==="
source $M/.venv/bin/activate
EP=http://127.0.0.1:8000/v1,http://127.0.0.1:8001/v1,http://127.0.0.1:8002/v1,http://127.0.0.1:8003/v1
for i in 0 1 2 3; do curl -sf "http://127.0.0.1:$((8000 + i))/v1/models" >/dev/null || echo "SERVER_DOWN $i"; done
python $M/run_matrix.py --arms T1_harvest=$M/arms/T1_harvest --task-file $M/train_tasks.txt --first-sample 0 --samples 12 --time-scale 0.75 \
  --endpoints "$EP" --workers-per-endpoint 5 --data-root $D --image swegemma-framework:matrix --out $OUT --seed 1
echo "HARVEST2 resolved: $(grep -l "\"resolved\": true" $OUT/s*/T1_harvest/*/job_summary.json 2>/dev/null | wc -l) / $(ls $OUT/s*/T1_harvest/*/job_summary.json 2>/dev/null | wc -l)"
echo HARVEST2_DONE
