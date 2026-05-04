#!/usr/bin/env bash
# K10 ワーカーへの動画データ差分同期スクリプト (INFRA Phase D)
#
# 前提:
#   - K10 は Wi-Fi 接続前提 (NFS は使用しない)
#   - rsync による差分同期 + ログ出力
# 環境変数:
#   K10_HOST       : 例 k10.local
#   K10_USER       : 例 ss
#   SS_VIDEO_ROOT  : ローカル動画ルート (例 /path/to/shuttlescope/videos)
set -euo pipefail

: "${K10_HOST:?K10_HOST が未設定です}"
: "${K10_USER:?K10_USER が未設定です}"
: "${SS_VIDEO_ROOT:?SS_VIDEO_ROOT が未設定です}"

REMOTE_ROOT="${K10_REMOTE_ROOT:-/home/${K10_USER}/shuttlescope/videos}"
LOG_DIR="${SS_LOG_DIR:-./logs}"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/sync_videos_to_k10_$(date +%Y%m%d_%H%M%S).log"

echo "[sync] from=${SS_VIDEO_ROOT} to=${K10_USER}@${K10_HOST}:${REMOTE_ROOT}" | tee -a "${LOG_FILE}"

rsync -avh --partial --progress --delete-after \
  --exclude='*.tmp' --exclude='.DS_Store' \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  "${SS_VIDEO_ROOT}/" \
  "${K10_USER}@${K10_HOST}:${REMOTE_ROOT}/" 2>&1 | tee -a "${LOG_FILE}"

echo "[sync] done" | tee -a "${LOG_FILE}"
