#!/usr/bin/env bash
# Grade gold (and optionally empty) patches for every task in a list, P at a time.
# Usage: run_controls.sh TASK_FILE OUT_DIR [P] [MODES]
set -uo pipefail
M=$HOME/matrix; source "$M/.venv/bin/activate"
TASKS=$1; OUT=$2; P=${3:-8}; MODES=${4:-gold}
D=$HOME/competition/competition_data
for mode in $MODES; do
  xargs -P "$P" -I{} sh -c "[ -f '$OUT/$mode/{}/job_summary.json' ] || python '$M/run_one.py' --control $mode \
    --arm-dir '$M/arms/A_recipe' --task-id {} --data-root '$D' --image swegemma-framework:matrix \
    --endpoint http://127.0.0.1:9/v1 --out '$OUT/$mode/{}' > /dev/null 2>&1; \
    echo $mode {} \$(python -c \"import json;print(json.load(open('$OUT/$mode/{}/job_summary.json'))['resolved'])\" 2>/dev/null || echo NO_SUMMARY)" \
    < "$TASKS"
done
