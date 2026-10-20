#!/bin/bash
# Wait for the diagnostic smoke to finish, record it, then run the main contrasts.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
log() { echo "[$(date +%m-%d_%H:%M:%S)] $*"; }

alive() { pgrep -f "scripts/run_study.py --plan experiments/$1" >/dev/null 2>&1; }

log "waiting for smoke (mtb + civic)"
while alive v1_mtb_smoke_api5000 || alive v1_civic_smoke_api5000 \
      || [ ! -f results/v1/real_mtb_smoke/study.json ] || [ ! -f results/v1/real_civic_smoke/study.json ]; do
  if ! alive v1_mtb_smoke_api5000 && ! alive v1_civic_smoke_api5000 \
     && { [ ! -f results/v1/real_mtb_smoke/study.json ] || [ ! -f results/v1/real_civic_smoke/study.json ]; }; then
    log "smoke runners gone but study.json missing -> recording partial state and continuing"
    break
  fi
  sleep 60
done

for s in real_mtb_smoke real_civic_smoke; do
  [ -d "results/v1/$s" ] && .venv/bin/python scripts/real_metrics.py --study "results/v1/$s" \
    --inputs "data/mtbbench/inputs.jsonl" --out "results/v1/${s}_metrics.json" --citations 6 \
    > "results/v1/${s}_metrics.txt" 2>&1 && log "metrics $s -> $(tail -1 results/v1/${s}_metrics.txt)"
done

log "launching main contrasts (repair1)"
setsid nohup bash results/v1/probes/run_real_smoke.sh v1_mtb_dev_main_api5000_repair1.json mtbbench real_mtb_main_repair1 10 \
  > results/v1/probes/real_mtb_main_repair1.log 2>&1 < /dev/null &
sleep 5
setsid nohup bash results/v1/probes/run_real_smoke.sh v1_civic_dev_main_api5000_repair1.json civicfact-pmidids real_civic_main_repair1 6 \
  > results/v1/probes/real_civic_main_repair1.log 2>&1 < /dev/null &

log "waiting for main contrasts"
while alive v1_mtb_dev_main_api5000_repair1 || alive v1_civic_dev_main_api5000_repair1; do sleep 120; done

for pair in "real_mtb_main_repair1:data/mtbbench/inputs.jsonl" "real_civic_main_repair1:data/civicfact-pmidids/inputs.jsonl"; do
  s=${pair%%:*}; inp=${pair#*:}
  [ -f "results/v1/$s/study.json" ] && .venv/bin/python scripts/real_metrics.py --study "results/v1/$s" \
    --inputs "$inp" --out "results/v1/${s}_metrics.json" --citations 8 > "results/v1/${s}_metrics.txt" 2>&1 \
    && log "metrics $s -> $(tail -1 results/v1/${s}_metrics.txt)"
done
log "chain complete"
