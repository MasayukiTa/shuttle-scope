#!/usr/bin/env bash
# K10 上で Ray worker を起動する (INFRA Phase D)
#   num_cpus=14, num_gpus=0
# 環境変数:
#   SS_RAY_HEAD : head のアドレス (例 x1ai.local:6379)
set -euo pipefail

: "${SS_RAY_HEAD:?SS_RAY_HEAD が未設定 (例 x1ai.local:6379)}"

echo "[ray_worker] connecting to head=${SS_RAY_HEAD}"
ray start \
  --address="${SS_RAY_HEAD}" \
  --num-cpus=14 \
  --num-gpus=0 \
  --disable-usage-stats

echo "[ray_worker] worker joined."
