"""ONNX Runtime GPU (CUDA / TensorRT EP) が依存 DLL を見つけられるようにする。

PyTorch 同梱の CUDA/cuDNN ランタイム (torch/lib: cudnn64_9.dll, cudart64_12.dll,
cublas64_12.dll 等) や tensorrt_libs / pip の nvidia-* パッケージは site-packages
配下にあるが PATH には載っていない。Windows は Python 3.8+ の secure DLL search の
ため、PATH だけでなく os.add_dll_directory() で明示登録しないと
onnxruntime-gpu が CUDA/TensorRT EP をロードできず CPU にフォールバックする
(= 単体 CV スクリプトが極端に遅くなる原因)。

backend/main.py はサービス起動時に同等の torch/lib 登録を行っているが、
generate_tracking_debug_video.py 等の単体スクリプトは main.py を経由しないため、
CV 推論モジュール側の import 時にも本関数を呼んで同じ状態を保証する。

冪等。失敗しても例外を投げない (CPU フォールバックで動作継続)。
"""
from __future__ import annotations

import glob
import os
import site
import sys

_DONE = False


def _site_packages_dirs() -> list[str]:
    cands: list[str] = []
    try:
        cands.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        cands.append(os.path.join(sys.prefix, "Lib", "site-packages"))
    except Exception:
        pass
    out: list[str] = []
    for c in cands:
        if c and os.path.isdir(c) and c not in out:
            out.append(c)
    return out


def ensure_gpu_dll_path() -> list[str]:
    """torch/lib・tensorrt_libs・nvidia-*/bin を DLL 検索パスへ登録する (冪等)。

    登録したディレクトリの一覧を返す (デバッグ用)。
    """
    global _DONE
    if _DONE:
        return []
    _DONE = True

    dirs: list[str] = []
    for sp in _site_packages_dirs():
        for sub in ("torch/lib", "tensorrt_libs"):
            p = os.path.join(sp, *sub.split("/"))
            if os.path.isdir(p):
                dirs.append(p)
        nvidia = os.path.join(sp, "nvidia")
        if os.path.isdir(nvidia):
            dirs.extend(glob.glob(os.path.join(nvidia, "*", "bin")))

    added: list[str] = []
    for d in dirs:
        try:
            if d not in os.environ.get("PATH", ""):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(d)
            added.append(d)
        except Exception:
            pass
    return added
