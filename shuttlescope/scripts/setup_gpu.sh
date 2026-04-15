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

echo "[setup_gpu] 完了。以下で動作確認:"
echo "  SS_USE_GPU=1 ${VENV_PY} -c 'import torch; print(torch.cuda.is_available())'"
