#!/bin/bash
# Re-baseline after the board-handle compaction: new output directories, both arms.
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
      note "$out launching ($misses/3) $plan on $dataset workers=$workers"
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
}

note "pipeline3 (compacted re-baseline) start"
run_until_done v1_fast_mtb_smoke mtbbench real_fast2_mtb 6
metrics real_fast2_mtb data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_smoke civicfact-pmidids real_fast2_civic 4
metrics real_fast2_civic data/civicfact-pmidids/inputs.jsonl
run_until_done v1_fast_mtb_control mtbbench real_fast2_mtb_control 6
metrics real_fast2_mtb_control data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_control civicfact-pmidids real_fast2_civic_control 4
metrics real_fast2_civic_control data/civicfact-pmidids/inputs.jsonl
$PY scripts/compare_arms.py --reference results/v1/real_fast2_mtb --candidate results/v1/real_fast2_mtb_control \
  --gold data/mtbbench/_gold/labels.jsonl --out results/v1/compare_mtb_fast2_vs_single_tools.json >/dev/null 2>&1 \
  && note "compare WROTE mtb fast2"
$PY scripts/compare_arms.py --reference results/v1/real_fast2_civic --candidate results/v1/real_fast2_civic_control \
  --gold data/civicfact-pmidids/_gold/labels.jsonl --out results/v1/compare_civic_fast2_vs_single_tools.json >/dev/null 2>&1 \
  && note "compare WROTE civic fast2"
note "PIPELINE3 COMPLETE"
