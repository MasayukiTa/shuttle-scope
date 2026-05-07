"""GPU 健康状態を取得するヘルスプローブ。

pynvml は関数内で try-import する (未インストール環境で backend を落とさない)。
戻り値は常に dict。available=False の場合は reason を含める。
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator

logger = logging.getLogger(__name__)

# rereview NEW-E fix: 旧コードは関数内で `if "_NVML_LOCK" not in globals(): ...` の
# lazy-init を行っており、複数スレッドが同時 probe で `globals()` 競合する可能性
# (= ロック自体が競合) があった。module top-level で初期化することで一発確定。
_NVML_LOCK = threading.Lock()

# 4th-review followup: cross-process race fix。
# API process (uvicorn) と pipeline worker process (`backend/pipeline/worker.py`)
# が両方とも nvmlInit / nvmlShutdown を呼ぶ。NVIDIA driver の同時 init/shutdown は
# プロセス間で undefined behavior を起こすことがあり、`probe()` の戻りが
# 偶発的に `nvmlInit failed: NVML_ERROR_UNINITIALIZED` になる事例を踏む。
# プロセス内 threading.Lock では塞げないため、ファイルベースの advisory lock を
# 重ねがけする (Windows: msvcrt.locking, POSIX: fcntl.flock)。
#
# ロック対象は短時間 (probe は 100ms 未満) なので blocking で良い。
# 取得失敗 (タイムアウト等) しても probe は続行する (lock は best-effort 扱い)。
_NVML_FILELOCK_PATH = Path(tempfile.gettempdir()) / "shuttlescope_nvml.lock"
_NVML_FILELOCK_TIMEOUT_SEC = 5.0


@contextmanager
def _nvml_cross_process_lock() -> Iterator[bool]:
    """nvmlInit/Shutdown を別プロセスと直列化するための advisory lock。

    yield 値は「ロック取得に成功したか」を示す bool。
    失敗時も probe は続行 (best-effort)。
    """
    fp = None
    locked = False
    try:
        _NVML_FILELOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fp = open(_NVML_FILELOCK_PATH, "a+b")
        deadline = time.monotonic() + _NVML_FILELOCK_TIMEOUT_SEC
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    fp.seek(0)
                    msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.05)
        if not locked:
            logger.warning(
                "gpu_health: NVML cross-process lock not acquired within %.1fs; proceeding best-effort",
                _NVML_FILELOCK_TIMEOUT_SEC,
            )
        yield locked
    except Exception as exc:  # pragma: no cover - filesystem 依存
        logger.warning("gpu_health: NVML lock open failed: %s; proceeding best-effort", exc)
        yield False
    finally:
        if fp is not None and locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    fp.seek(0)
                    msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
            except Exception:  # pragma: no cover
                pass
        if fp is not None:
            try:
                fp.close()
            except Exception:
                pass


def probe() -> Dict[str, Any]:
    """利用可能な NVIDIA GPU の状態を辞書で返す。

    失敗時は {"available": False, "reason": "..."} を返す。例外は投げない。
    """
    try:
        import pynvml  # type: ignore  # nvidia-ml-py パッケージが提供する
    except ImportError:
        return {"available": False, "reason": "nvidia-ml-py not installed"}

    # pipeline #5 fix + rereview NEW-E: module-level Lock で probe を直列化 (in-process)
    # 4th-review followup: 加えて cross-process advisory lock で worker と API を直列化
    with _NVML_LOCK:
        with _nvml_cross_process_lock():
            try:
                pynvml.nvmlInit()
            except Exception as exc:  # pragma: no cover - 環境依存
                return {"available": False, "reason": f"nvmlInit failed: {exc}"}
            return _probe_within_nvml_lock(pynvml)


def _probe_within_nvml_lock(pynvml) -> dict:
    """nvmlInit 済の状態で実行する probe 本体。"""

    try:
        count = pynvml.nvmlDeviceGetCount()
        if count == 0:
            return {"available": False, "reason": "no NVIDIA GPU detected"}

        devices = []
        for i in range(count):
            try:
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = None
                devices.append(
                    {
                        "index": i,
                        "name": name,
                        "vram_total_mb": int(mem.total / 1024 / 1024),
                        "vram_used_mb": int(mem.used / 1024 / 1024),
                        "vram_free_mb": int(mem.free / 1024 / 1024),
                        "util_gpu_pct": int(util.gpu),
                        "util_mem_pct": int(util.memory),
                        "temperature_c": temp,
                    }
                )
            except Exception as exc:  # pragma: no cover - 環境依存
                devices.append({"index": i, "error": str(exc)})

        return {"available": True, "device_count": count, "devices": devices}
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
