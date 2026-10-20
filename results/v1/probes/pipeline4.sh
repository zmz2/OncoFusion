#!/bin/bash
# Variance probe: both arms, seeds 0/1, inside one time window per study.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
PY=.venv/bin/python
note() { echo "[$(date +%m-%d_%H:%M:%S)] $*"; }
study_alive() { pgrep -f "run_study.py --plan experiments/$1" >/dev/null 2>&1; }

run_until_done() {
  local plan=$1 dataset=$2 out=$3 workers=$4 misses=0
  while true; do
    if [ -f "results/v1/$out/study.json" ]; then note "$out COMPLETE"; return 0; fi
    if study_alive "$plan.json"; then misses=0; else
      misses=$((misses + 1))
      if [ $misses -gt 3 ]; then note "$out ABANDONED"; return 1; fi
      note "$out launching ($misses/3) $plan workers=$workers"
      setsid nohup bash -c "cd /home/zhangmingzhou/BioOncoFusion
        set -a; . /home/zhangmingzhou/.config/oncofusion/real-api.env; set +a
        export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
        start=\$(date +%s)
        $PY -u scripts/run_study.py --plan experiments/$plan.json --dataset data/$dataset \
          --out results/v1/$out --allow-remote --workers $workers --resume
        echo \"exit=\$? wall_seconds=\$(( \$(date +%s) - start )) plan=$plan\"" \
        >> "results/v1/probes/${out}_resume.log" 2>&1 < /dev/null &
    fi
    sleep 120
  done
}

note "pipeline4 (variance probe) start"
run_until_done v1_fast_mtb_variance mtbbench real_var_mtb 6
$PY scripts/real_metrics.py --study results/v1/real_var_mtb --inputs data/mtbbench/inputs.jsonl \
  --out results/v1/real_var_mtb_metrics.json --citations 4 > results/v1/real_var_mtb_metrics.txt 2>&1 && note "metrics WROTE real_var_mtb"
run_until_done v1_fast_civic_variance civicfact-pmidids real_var_civic 4
$PY scripts/real_metrics.py --study results/v1/real_var_civic --inputs data/civicfact-pmidids/inputs.jsonl \
  --out results/v1/real_var_civic_metrics.json --citations 4 > results/v1/real_var_civic_metrics.txt 2>&1 && note "metrics WROTE real_var_civic"
note "PIPELINE4 COMPLETE"
