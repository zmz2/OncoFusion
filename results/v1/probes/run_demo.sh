#!/bin/bash
# Long-running real-API demo, detached from the SSH channel.
cd /home/zhangmingzhou/BioOncoFusion || exit 1
set -a
. /home/zhangmingzhou/.config/oncofusion/real-api.env
set +a
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
start=$(date +%s)
.venv/bin/python -u -m oncofusion demo --profile v1 --out results/v1/real_demo.json --allow-remote
rc=$?
echo "exit=$rc wall_seconds=$(( $(date +%s) - start ))"
