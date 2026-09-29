#!/usr/bin/env bash
# X1 AI 上で Ray head を起動する (INFRA Phase D)
#   num_cpus=8, num_gpus=1
set -euo pipefail

PORT="${SS_RAY_PORT:-6379}"
DASHBOARD_PORT="${SS_RAY_DASHBOARD_PORT:-8265}"

# Round 258 R7 P1 fix (Codex review):
# Ray の GCS (port) と dashboard は **無認証** で動くため、外部公開された瞬間に
# anyone-with-network-reach から RCE 可能 (cloudpickle で remote task 投入できる)。
# main.py 側では dashboard を 127.0.0.1 に倒しているが、本 script で `0.0.0.0` を
# 渡すとそれを迂回する。既定 loopback、明示 opt-in (SS_RAY_EXPOSE_UNAUTH=1) のときだけ
# `0.0.0.0` を許容する。本来は WireGuard / Cloudflare Access の背後でのみ公開すべき。
DASHBOARD_HOST="${SS_RAY_DASHBOARD_HOST:-127.0.0.1}"
if [ "${DASHBOARD_HOST}" = "0.0.0.0" ] && [ "${SS_RAY_EXPOSE_UNAUTH:-0}" != "1" ]; then
  echo "[ray_head] FATAL: dashboard-host=0.0.0.0 requires SS_RAY_EXPOSE_UNAUTH=1." >&2
  echo "  Ray dashboard / GCS have NO authentication. Exposing them on 0.0.0.0 grants" >&2
  echo "  RCE to anyone with network reach. Recommended: keep loopback and tunnel via" >&2
  echo "  WireGuard / Cloudflare Access / SSH local forwarding." >&2
  exit 2
fi

echo "[ray_head] starting head: port=${PORT} dashboard=${DASHBOARD_HOST}:${DASHBOARD_PORT}"
ray start --head \
  --port="${PORT}" \
  --dashboard-host="${DASHBOARD_HOST}" \
  --dashboard-port="${DASHBOARD_PORT}" \
  --num-cpus=8 \
  --num-gpus=1 \
  --disable-usage-stats

echo "[ray_head] head started. 接続先: ray://<this_host>:${PORT}"
