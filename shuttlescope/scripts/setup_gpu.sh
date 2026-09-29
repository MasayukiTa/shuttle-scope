#!/usr/bin/env bash
# ShuttleScope GPU セットアップスクリプト (Linux / WSL2)
# INFRA Phase A: CUDA 12.4 向け torch + mediapipe + pynvml をインストールする。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${REPO_ROOT}/backend/.venv/bin/python"

if [[ ! -x "${VENV_PY}" ]]; then
    echo "venv が見つかりません: ${VENV_PY}" >&2
    echo "先に backend/setup_venv.sh を実行してください" >&2
    exit 1
fi

echo "[setup_gpu] pip 更新"
"${VENV_PY}" -m pip install --upgrade pip

echo "[setup_gpu] PyTorch (CUDA 12.4) インストール"
"${VENV_PY}" -m pip install --index-url https://download.pytorch.org/whl/cu124 \
    "torch==2.4.*" torchvision

echo "[setup_gpu] MediaPipe / pynvml インストール"
"${VENV_PY}" -m pip install "mediapipe>=0.10.14" pynvml

# 任意: ONNX Runtime GPU
echo "[setup_gpu] (任意) onnxruntime-gpu"
"${VENV_PY}" -m pip install onnxruntime-gpu || true

# MediaPipe Pose モデルファイルの自動ダウンロード
MODEL_DIR="${REPO_ROOT}/backend/cv/models"
MODEL_PATH="${MODEL_DIR}/pose_landmarker_lite.task"
MODEL_URL="https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
if [[ ! -f "${MODEL_PATH}" ]]; then
    echo "[setup_gpu] MediaPipe Pose モデルをダウンロード中..."
    mkdir -p "${MODEL_DIR}"
    if command -v curl &>/dev/null; then
        curl -fL -o "${MODEL_PATH}" "${MODEL_URL}" || {
            echo "[setup_gpu] WARNING: モデルダウンロード失敗。手動でダウンロードしてください:" >&2
            echo "  ${MODEL_URL}" >&2
        }
    elif command -v wget &>/dev/null; then
        wget -q -O "${MODEL_PATH}" "${MODEL_URL}" || {
            echo "[setup_gpu] WARNING: モデルダウンロード失敗。手動でダウンロードしてください:" >&2
            echo "  ${MODEL_URL}" >&2
        }
    else
        echo "[setup_gpu] WARNING: curl / wget が見つかりません。モデルを手動配置してください: ${MODEL_PATH}" >&2
    fi
else
    echo "[setup_gpu] MediaPipe モデル既存: ${MODEL_PATH}"
fi

echo "[setup_gpu] 完了。以下で動作確認:"
echo "  SS_USE_GPU=1 ${VENV_PY} -c 'import torch; print(torch.cuda.is_available())'"
echo "  SS_USE_GPU=1 ${VENV_PY} -c 'from backend.cv.factory import get_tracknet; print(type(get_tracknet()).__name__)'"
