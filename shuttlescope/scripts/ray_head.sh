#!/usr/bin/env bash
# X1 AI 上で Ray head を起動する (INFRA Phase D)
#   num_cpus=8, num_gpus=1
set -euo pipefail

PORT="${SS_RAY_PORT:-6379}"
DASHBOARD_PORT="${SS_RAY_DASHBOARD_PORT:-8265}"

echo "[ray_head] starting head: port=${PORT} dashboard=${DASHBOARD_PORT}"
ray start --head \
  --port="${PORT}" \
  --dashboard-host=0.0.0.0 \
  --dashboard-port="${DASHBOARD_PORT}" \
  --num-cpus=8 \
  --num-gpus=1 \
  --disable-usage-stats

echo "[ray_head] head started. 接続先: ray://<this_host>:${PORT}"
