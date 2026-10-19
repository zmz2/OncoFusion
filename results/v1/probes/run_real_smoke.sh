#!/bin/bash
# Real-API three-system smoke, detached from the SSH channel.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
set -a
. /home/zhangmingzhou/.config/oncofusion/real-api.env
set +a
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
plan=$1; dataset=$2; out=$3; workers=$4
start=$(date +%s)
.venv/bin/python -u scripts/run_study.py --plan "experiments/$plan" --dataset "data/$dataset" \
  --out "results/v1/$out" --allow-remote --workers "$workers"
echo "exit=$? wall_seconds=$(( $(date +%s) - start )) plan=$plan workers=$workers"
