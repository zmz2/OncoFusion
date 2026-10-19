#!/bin/bash
# v2: the restart counter only advances while the runner is actually missing.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
PY=.venv/bin/python
note() { echo "[$(date +%m-%d_%H:%M:%S)] $*"; }
study_alive() { pgrep -f "run_study.py --plan experiments/$1" >/dev/null 2>&1; }

run_until_done() {
  local plan=$1 dataset=$2 out=$3 workers=$4 misses=0
  while true; do
    if [ -f "results/v1/$out/study.json" ]; then note "$out COMPLETE"; return 0; fi
    if study_alive "$plan.json"; then
      misses=0
    else
      misses=$((misses + 1))
      if [ $misses -gt 3 ]; then note "$out ABANDONED after $misses missing-runner checks"; return 1; fi
      note "$out runner missing (restart $misses/3): resuming $plan on $dataset workers=$workers"
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

metrics() {
  local out=$1 inputs=$2
  [ -f "results/v1/$out/study.json" ] || { note "metrics SKIPPED $out"; return 1; }
  $PY scripts/real_metrics.py --study "results/v1/$out" --inputs "$inputs" \
    --out "results/v1/${out}_metrics.json" --citations 8 > "results/v1/${out}_metrics.txt" 2>&1 \
    && note "metrics WROTE $out" || note "metrics FAILED $out"
  mkdir -p results/v1/review
  $PY scripts/review_citations.py export --study "results/v1/$out" --inputs "$inputs" \
    --out "results/v1/review/$out" --limit 12 > "results/v1/review/${out}_export.log" 2>&1 \
    && note "review export WROTE $out" || note "review export FAILED $out"
}

note "pipeline v2 start"
run_until_done v1_fast_mtb_smoke mtbbench real_fast_mtb 6
metrics real_fast_mtb data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_smoke civicfact-pmidids real_fast_civic 4
metrics real_fast_civic data/civicfact-pmidids/inputs.jsonl
note "starting single_tools controls"
run_until_done v1_fast_mtb_control mtbbench real_fast_mtb_control 6
metrics real_fast_mtb_control data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_control civicfact-pmidids real_fast_civic_control 4
metrics real_fast_civic_control data/civicfact-pmidids/inputs.jsonl
note "PIPELINE COMPLETE"
