"""MediaPipe 姿勢推定ランナー（cluster/tasks.py から呼ばれるエントリポイント）。

`factory.get_pose()` 経由でバックエンド（CUDA GPU delegate / CPU）を選択し、
動画ファイルに対して姿勢推定を実行する。

X1 AI（SS_USE_GPU=1）では MediaPipe GPU delegate、K10 では CPU MediaPipe を使う。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def run_mediapipe(video_path: str, **kwargs: Any) -> Dict[str, Any]:
    """動画を MediaPipe Pose で解析し、姿勢推定結果を返す。

    Args:
        video_path: 解析対象動画のパス
        **kwargs: 将来の拡張（match_id, player_side 等）

    Returns:
        {
            "status": "ok" | "error",
            "backend": str,           # 使用したバックエンド名
            "sample_count": int,      # 取得したフレーム数
            "samples": List[dict],    # PoseSample を dict 化したもの
        }
    """
    from backend.cv.factory import get_pose

    try:
        inferencer = get_pose()
        backend_name = type(inferencer).__name__

        logger.info("[mediapipe_runner] %s で推論開始: %s", backend_name, video_path)
        samples = inferencer.run(video_path)
        logger.info("[mediapipe_runner] 完了: %d サンプル", len(samples))

        return {
            "status": "ok",
            "backend": backend_name,
            "sample_count": len(samples),
            "samples": [
                {
                    "frame": s.frame,
                    "ts_sec": s.ts_sec,
                    "side": s.side,
                    "landmarks": s.landmarks,
                }
                for s in samples
            ],
        }
    except Exception as exc:
        logger.exception("[mediapipe_runner] 推論失敗: %s", exc)
        return {"status": "error", "error": str(exc)}
