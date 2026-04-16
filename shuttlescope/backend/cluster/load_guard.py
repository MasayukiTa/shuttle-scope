"""負荷ガード: GPU / CPU 使用率の監視と推論タスクのスロットリング (INFRA Phase D)

使い方:
    guard = LoadGuard()
    if not guard.can_accept():
        raise HTTPException(503, "負荷上限に達しています")
    with guard.task_slot():
        # 推論処理
        ...
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Dict, Optional

from backend.cluster.topology import get_load_limits

logger = logging.getLogger(__name__)


class LoadGuard:
    """GPU / CPU 使用率と同時実行数を監視してタスク受付を制御するシングルトン。"""

    _instance: Optional["LoadGuard"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "LoadGuard":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self) -> None:
        self._active = 0
        self._active_lock = threading.Lock()

    # ────────────────────────────────────────────────────────────────────────
    # 使用率プローブ
    # ────────────────────────────────────────────────────────────────────────

    def _cpu_percent(self) -> float:
        """現在の CPU 使用率（%）を返す。psutil 未インストール時は 0.0。"""
        try:
            import psutil  # type: ignore
            return psutil.cpu_percent(interval=0.2)
        except Exception:
            return 0.0

    def _gpu_percent(self) -> float:
        """NVIDIA GPU 使用率（%）を返す。取得不可なら 0.0。"""
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            return float(util.gpu)
        except Exception:
            return 0.0

    # ────────────────────────────────────────────────────────────────────────
    # 公開 API
    # ────────────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, object]:
        """現在の負荷状況を返す（ヘルスエンドポイント向け）。"""
        limits = get_load_limits()
        cpu = self._cpu_percent()
        gpu = self._gpu_percent()
        max_inf = int(limits.get("max_concurrent_inference", 4))
        return {
            "cpu_percent": round(cpu, 1),
            "gpu_percent": round(gpu, 1),
            "active_tasks": self._active,
            "max_concurrent_inference": max_inf,
            "cpu_limit": limits.get("max_cpu_percent", 70),
            "gpu_limit": limits.get("max_gpu_percent", 80),
            "cpu_ok": cpu < float(limits.get("max_cpu_percent", 70)),
            "gpu_ok": gpu < float(limits.get("max_gpu_percent", 80)),
            "slots_ok": self._active < max_inf,
        }

    def can_accept(self) -> bool:
        """新規タスクを受け付けられるか判定する。"""
        s = self.status()
        return bool(s["cpu_ok"]) and bool(s["gpu_ok"]) and bool(s["slots_ok"])

    @contextmanager
    def task_slot(self):
        """with 構文でタスク数カウントを管理するコンテキストマネージャ。

        使用例:
            with load_guard.task_slot():
                result = run_inference(...)
        """
        with self._active_lock:
            self._active += 1
        try:
            yield
        finally:
            with self._active_lock:
                self._active = max(0, self._active - 1)

    def wait_until_available(self, timeout: float = 30.0) -> bool:
        """負荷が下がるまで最大 timeout 秒待機する。

        タイムアウト時は False を返す。
        """
        limits = get_load_limits()
        interval = float(limits.get("throttle_interval_sec", 1.0))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.can_accept():
                return True
            logger.debug("load_guard: 過負荷待機中 (active=%d)", self._active)
            time.sleep(interval)
        return False


# モジュールレベルのシングルトン
load_guard = LoadGuard()
