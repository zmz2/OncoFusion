#!/bin/bash
# Keeps the real-API stage moving: finish v1_fast runs, emit metrics, then run the single_tools controls.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
PY=.venv/bin/python
note() { echo "[$(date +%m-%d_%H:%M:%S)] $*"; }

# plan dataset out workers
study_alive() { pgrep -f "run_study.py --plan experiments/$1" >/dev/null 2>&1; }

run_until_done() {           # $1 plan $2 dataset $3 outdir $4 workers
  local plan=$1 dataset=$2 out=$3 workers=$4 attempt=1
  while true; do
    if [ -f "results/v1/$out/study.json" ]; then note "$out complete"; return 0; fi
    if study_alive "$plan.json"; then note "$out runner alive (attempt $attempt)"; else
      if [ $attempt -ge 4 ]; then note "$out giving up after $attempt attempts"; return 1; fi
      note "$out launching/resuming $plan on $dataset workers=$workers attempt=$attempt"
      setsid nohup bash -c "cd /home/zhangmingzhou/BioOncoFusion
        set -a; . /home/zhangmingzhou/.config/oncofusion/real-api.env; set +a
        export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
        start=\$(date +%s)
        $PY -u scripts/run_study.py --plan experiments/$plan.json --dataset data/$dataset \
          --out results/v1/$out --allow-remote --workers $workers --resume
        echo \"exit=\$? wall_seconds=\$(( \$(date +%s) - start )) plan=$plan\"" \
        >> "results/v1/probes/${out}_resume.log" 2>&1 < /dev/null &
      sleep 30
    fi
    attempt=$((attempt + 1)); sleep 120
  done
}

metrics() {                  # $1 outdir $2 inputs
  local out=$1 inputs=$2
  [ -f "results/v1/$out/study.json" ] || { note "metrics skipped $out (no study.json)"; return 1; }
  $PY scripts/real_metrics.py --study "results/v1/$out" --inputs "$inputs" \
    --out "results/v1/${out}_metrics.json" --citations 8 > "results/v1/${out}_metrics.txt" 2>&1 \
    && note "metrics $out written" || note "metrics $out FAILED"
  $PY scripts/review_citations.py export --study "results/v1/$out" --inputs "$inputs" \
    --out "results/v1/review/$out" --limit 12 > "results/v1/review/${out}_export.log" 2>&1 \
    && note "review export $out written" || note "review export $out failed (see log)"
}

mkdir -p results/v1/review
note "pipeline start"
run_until_done v1_fast_mtb_smoke mtbbench real_fast_mtb 6
metrics real_fast_mtb data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_smoke civicfact-pmidids real_fast_civic 4
metrics real_fast_civic data/civicfact-pmidids/inputs.jsonl
note "v1_fast arms done; starting single_tools controls"
run_until_done v1_fast_mtb_control mtbbench real_fast_mtb_control 6
metrics real_fast_mtb_control data/mtbbench/inputs.jsonl
run_until_done v1_fast_civic_control civicfact-pmidids real_fast_civic_control 4
metrics real_fast_civic_control data/civicfact-pmidids/inputs.jsonl
note "PIPELINE COMPLETE"
