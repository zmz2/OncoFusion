#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a
. "${ONCOFUSION_REAL_ENV:-$HOME/.config/oncofusion/real-api.env}"
set +a
export PYTHONPATH=.
export ONCOFUSION_SEND_TEMPERATURE=true ONCOFUSION_SEND_SEED=true
export ONCOFUSION_API_CONCURRENCY=20
exec "${ONCOFUSION_PYTHON:-/home/zhangmingzhou/BioOncoFusion/.venv/bin/python}" scripts/serve_classroom_v2.py \
  --root "${ONCOFUSION_CLASSROOM_ROOT:-/home/zhangmingzhou/BioOncoFusion/runtime/classroom_web_v2_20261110}" \
  --port "${ONCOFUSION_CLASSROOM_PORT:-8181}"
