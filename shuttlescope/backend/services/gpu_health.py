"""GPU 健康状態を取得するヘルスプローブ。

pynvml は関数内で try-import する (未インストール環境で backend を落とさない)。
戻り値は常に dict。available=False の場合は reason を含める。
"""
from __future__ import annotations

import threading
from typing import Any, Dict

# rereview NEW-E fix: 旧コードは関数内で `if "_NVML_LOCK" not in globals(): ...` の
# lazy-init を行っており、複数スレッドが同時 probe で `globals()` 競合する可能性
# (= ロック自体が競合) があった。module top-level で初期化することで一発確定。
_NVML_LOCK = threading.Lock()


def probe() -> Dict[str, Any]:
    """利用可能な NVIDIA GPU の状態を辞書で返す。

    失敗時は {"available": False, "reason": "..."} を返す。例外は投げない。
    """
    try:
        import pynvml  # type: ignore  # nvidia-ml-py パッケージが提供する
    except ImportError:
        return {"available": False, "reason": "nvidia-ml-py not installed"}

    # pipeline #5 fix + rereview NEW-E: module-level Lock で probe を直列化。
    # cross-process race (API + worker) はプロセス内 Lock では解決できないため
    # 別 NORMAL TODO として残す (file-lock or DB advisory lock 等)。
    with _NVML_LOCK:
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
