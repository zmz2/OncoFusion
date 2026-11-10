#!/usr/bin/env bash
set -u

root="$HOME/BioOncoFusion"
run_name="${1:-real_expand_calibrate_20261108}"
run_root="$root/results/v1/$run_name"
mkdir -p "$run_root"
cd "$root" || exit 1
set -a
. "$HOME/.config/oncofusion/real-api.env"
set +a

status=0
.venv/bin/python scripts/run_study.py \
  --plan experiments/v1_calibrate_mtb2.json \
  --dataset data/mtbbench \
  --out "$run_root/mtb" \
  --allow-remote \
  --workers 2 \
  --execution-cap 4 >"$run_root/mtb.log" 2>&1
mtb_status=$?
[ "$mtb_status" -eq 0 ] || status=1

.venv/bin/python scripts/run_study.py \
  --plan experiments/v1_calibrate_civic3.json \
  --dataset data/civicfact-pmidids \
  --out "$run_root/civic" \
  --allow-remote \
  --workers 2 \
  --execution-cap 6 >"$run_root/civic.log" 2>&1
civic_status=$?
[ "$civic_status" -eq 0 ] || status=1

printf '{"mtb_exit":%d,"civic_exit":%d,"status":%s}\n' \
  "$mtb_status" "$civic_status" "$([ "$status" -eq 0 ] && printf true || printf false)" \
  >"$run_root/status.json"
exit "$status"
