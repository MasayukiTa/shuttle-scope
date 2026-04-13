"""CV モデルベンチマーク API（/api/cv/benchmark）

エンドポイント:
  POST /api/cv/benchmark  — YOLO + TrackNet の推論速度を計測して返す（約10秒）
"""
import asyncio
import logging
import time

import numpy as np
from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter()

# 計測に使う合成フレーム数（少なめにして約10秒以内に収める）
_YOLO_SAMPLES = 30
_TN_SAMPLES   = 30
_FRAME_W, _FRAME_H = 1920, 1080


def _make_pool(n: int) -> list[np.ndarray]:
    """合成フレームプールを生成（キャッシュヒット防止のためフレームごとにノイズを変える）"""
    rng = np.random.default_rng(42)
    base = np.full((_FRAME_H, _FRAME_W, 3), [40, 120, 40], dtype=np.uint8)
    pool = []
    for _ in range(n):
        noise = rng.integers(0, 60, (_FRAME_H, _FRAME_W, 3), dtype=np.uint8)
        pool.append(np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8))
    return pool


def _run_benchmark() -> dict:
    """同期ベンチマーク処理（スレッドプールで実行される）"""
    pool = _make_pool(max(_YOLO_SAMPLES, _TN_SAMPLES))

    # ─── YOLO ─────────────────────────────────────────────────────────────────
    yolo_result: dict = {"error": "未計測"}
    try:
        from backend.yolo.inference import get_yolo_inference
        inf_y = get_yolo_inference()
        if inf_y.load():
            latencies = []
            for i in range(_YOLO_SAMPLES):
                t0 = time.perf_counter()
                inf_y.predict_frame(pool[i % len(pool)])
                latencies.append(time.perf_counter() - t0)
            avg_ms = float(np.mean(latencies)) * 1000
            yolo_result = {
                "fps": round(1000.0 / avg_ms, 2),
                "avg_ms": round(avg_ms, 1),
                "p95_ms": round(float(np.percentile(latencies, 95)) * 1000, 1),
                "backend": inf_y.backend_name(),
                "samples": _YOLO_SAMPLES,
            }
        else:
            yolo_result = {"error": inf_y.get_load_error() or "モデルロード失敗"}
    except Exception as e:
        logger.warning("YOLO benchmark failed: %s", e)
        yolo_result = {"error": str(e)}

    # ─── TrackNet ─────────────────────────────────────────────────────────────
    tn_result: dict = {"error": "未計測"}
    try:
        from backend.tracknet.inference import get_inference
        inf_t = get_inference("auto")
        if inf_t.load():
            latencies = []
            for i in range(_TN_SAMPLES):
                triplet = [pool[(i + j) % len(pool)] for j in range(3)]
                t0 = time.perf_counter()
                inf_t.predict_frames(triplet)
                latencies.append(time.perf_counter() - t0)
            avg_ms = float(np.mean(latencies)) * 1000
            tn_result = {
                "fps": round(1000.0 / avg_ms, 2),
                "avg_ms": round(avg_ms, 1),
                "p95_ms": round(float(np.percentile(latencies, 95)) * 1000, 1),
                "backend": inf_t.backend_name(),
                "samples": _TN_SAMPLES,
            }
        else:
            tn_result = {"error": inf_t.get_load_error() or "モデルロード失敗"}
    except Exception as e:
        logger.warning("TrackNet benchmark failed: %s", e)
        tn_result = {"error": str(e)}

    return {"yolo": yolo_result, "tracknet": tn_result}


@router.post("/cv/benchmark")
async def run_cv_benchmark():
    """YOLO + TrackNet の推論速度を計測して返す（約10秒）。
    推論はスレッドプールで実行するため FastAPI イベントループをブロックしない。
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_benchmark)
    return {"success": True, "data": result}
