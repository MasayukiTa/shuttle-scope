"""TrackNet 推論ランナー（cluster/tasks.py から呼ばれるエントリポイント）。

`factory.get_tracknet()` 経由でバックエンド（CUDA / OpenVINO / CPU）を選択し、
動画ファイルに対してシャトル軌跡推定を実行する。

Ray タスクからも通常呼び出しからも同じ関数を使う。
バックエンド選択は factory に任せるため、このファイルは薄く保つ。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def run_tracknet(video_path: str, **kwargs: Any) -> Dict[str, Any]:
    """動画を TrackNet で解析し、シャトル軌跡と統計を返す。

    Args:
        video_path: 解析対象動画のパス
        **kwargs: 将来の拡張（match_id 等）

    Returns:
        {
            "status": "ok" | "error",
            "backend": str,           # 使用したバックエンド名
            "sample_count": int,      # 取得したフレーム数
            "samples": List[dict],    # ShuttleSample を dict 化したもの
            "rally_bounds": ...       # 将来実装: ラリー境界推定結果
        }
    """
    from backend.cv.factory import get_tracknet

    try:
        inferencer = get_tracknet()
        backend_name = type(inferencer).__name__

        logger.info("[tracknet_runner] %s で推論開始: %s", backend_name, video_path)
        samples = inferencer.run(video_path)
        logger.info("[tracknet_runner] 完了: %d サンプル", len(samples))

        return {
            "status": "ok",
            "backend": backend_name,
            "sample_count": len(samples),
            "samples": [
                {
                    "frame": s.frame,
                    "ts_sec": s.ts_sec,
                    "x": s.x,
                    "y": s.y,
                    "confidence": s.confidence,
                }
                for s in samples
            ],
            "rally_bounds": None,  # TODO: ラリー境界推定を実装後に追加
        }
    except Exception as exc:
        logger.exception("[tracknet_runner] 推論失敗: %s", exc)
        return {"status": "error", "error": str(exc)}
