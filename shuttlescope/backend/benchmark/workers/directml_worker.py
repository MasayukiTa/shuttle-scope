"""DirectML ベンチマーク ワーカー — onnxruntime-directml 専用 venv で実行する standalone スクリプト。

runner.py から subprocess として起動される。
stdin: JSON パラメータ
stdout: JSON 結果 {"latencies": [...], "chosen_batch": N, "providers": [...]}
        or         {"error": "..."}

パラメータスキーマ:
    model_path  : str  — ONNX モデルの絶対パス
    input_shape : list — [B, C, H, W] (B はスイープ時の初期値 or 固定値)
    in_dtype    : str  — "float32" | "float16"
    warmup      : int  — ウォームアップ回数 (default 3)
    min_iters   : int  — 最低計測回数 (default 5)
    budget_sec  : float — 計測予算 (秒, default 5.0)
    max_iters   : int  — 最大計測回数 (default 500)
    batch_sweep : list — バッチスイープ候補 (省略時は input_shape[0] 固定)
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

import numpy as np


def _measure(sess, input_name: str, x: np.ndarray, warmup: int,
             min_iters: int, budget_sec: float, max_iters: int) -> list[float]:
    """warmup → 時間予算ベース計測。"""
    for _ in range(warmup):
        try:
            sess.run(None, {input_name: x})
        except Exception:
            break
    lats: list[float] = []
    t_start = time.perf_counter()
    while True:
        if len(lats) >= max_iters:
            break
        if len(lats) >= min_iters and (time.perf_counter() - t_start) >= budget_sec:
            break
        t0 = time.perf_counter()
        sess.run(None, {input_name: x})
        lats.append(time.perf_counter() - t0)
    return lats


def main() -> None:
    raw = sys.stdin.read()
    try:
        params: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        print(json.dumps({"error": f"JSON parse error: {exc}"}))
        return

    model_path: str = params["model_path"]
    input_shape: list[int] = params["input_shape"]
    in_dtype_str: str = params.get("in_dtype", "float32")
    warmup: int = params.get("warmup", 3)
    min_iters: int = params.get("min_iters", 5)
    budget_sec: float = params.get("budget_sec", 5.0)
    max_iters: int = params.get("max_iters", 500)
    batch_sweep: list[int] | None = params.get("batch_sweep", None)

    dtype = np.float16 if "float16" in in_dtype_str else np.float32

    try:
        import onnxruntime as ort  # noqa: PLC0415
    except ImportError as exc:
        print(json.dumps({"error": f"onnxruntime import failed: {exc}"}))
        return

    avail = ort.get_available_providers()
    if "DmlExecutionProvider" not in avail:
        print(json.dumps({
            "error": f"DmlExecutionProvider 利用不可 — avail={avail}",
        }))
        return

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.enable_mem_pattern = True
    so.enable_mem_reuse = True

    try:
        sess = ort.InferenceSession(
            model_path, sess_options=so,
            providers=["DmlExecutionProvider", "CPUExecutionProvider"],
        )
    except Exception as exc:
        print(json.dumps({"error": f"セッション初期化失敗: {exc}"}))
        return

    input_name: str = sess.get_inputs()[0].name
    actual_providers: list[str] = sess.get_providers()

    # ── バッチスイープで最適バッチを選ぶ ────────────────────────────────────────
    if batch_sweep and len(batch_sweep) > 1:
        best_per_sample: float | None = None
        best_batch: int = batch_sweep[0]
        for b in batch_sweep:
            shape = list(input_shape)
            shape[0] = b
            x = np.zeros(shape, dtype=dtype)
            try:
                # 2 回ウォームアップ + 3 回計測
                sess.run(None, {input_name: x})
                sess.run(None, {input_name: x})
                sweep_lats: list[float] = []
                for _ in range(3):
                    t0 = time.perf_counter()
                    sess.run(None, {input_name: x})
                    sweep_lats.append(time.perf_counter() - t0)
                avg = float(np.mean(sweep_lats))
                per_sample = avg / b
                if best_per_sample is None or per_sample < best_per_sample:
                    best_per_sample = per_sample
                    best_batch = b
            except Exception:
                # OOM 等: このバッチサイズは諦めて前の結果で止まる
                break
        chosen_batch = best_batch
    else:
        chosen_batch = input_shape[0]

    # ── 本計測 ───────────────────────────────────────────────────────────────────
    shape = list(input_shape)
    shape[0] = chosen_batch
    x = np.zeros(shape, dtype=dtype)

    lats = _measure(sess, input_name, x, warmup, min_iters, budget_sec, max_iters)

    print(json.dumps({
        "latencies": lats,
        "chosen_batch": chosen_batch,
        "providers": actual_providers,
    }))


if __name__ == "__main__":
    main()
