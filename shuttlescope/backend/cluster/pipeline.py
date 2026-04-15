"""ビデオ解析パイプライン (INFRA Phase D)

Vol.2 §3.3 準拠:
  TrackNet / MediaPipe を並列 → extract_clips → statistics / CoG / shot 分類
Ray 未起動時は同期フォールバック。
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from backend.config import settings

from . import tasks as _tasks
from .bootstrap import is_ray_available

logger = logging.getLogger(__name__)


def _ray_live() -> bool:
    """現在 Ray が初期化済みで利用可能か"""
    if not is_ray_available():
        return False
    try:
        import ray  # type: ignore
        return bool(ray.is_initialized())
    except Exception:
        return False


def _get(result: Any) -> Any:
    """ray ObjectRef なら ray.get、そうでなければそのまま返す"""
    try:
        import ray  # type: ignore
        if isinstance(result, ray.ObjectRef):  # type: ignore[attr-defined]
            return ray.get(result)
    except Exception:
        pass
    return result


def _call(task_fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Ray 利用可能なら .remote、それ以外は同期呼び出し"""
    if _ray_live() and hasattr(task_fn, "remote"):
        return task_fn.remote(*args, **kwargs)
    return task_fn(*args, **kwargs)


def run_video_analysis_pipeline(video_id: int, video_path: str) -> Dict[str, Any]:
    """動画解析パイプラインのエントリポイント。

    - SS_CLUSTER_MODE=ray かつ Ray 起動済みなら分散実行
    - それ以外は同一プロセスで逐次実行 (フォールバック)
    - 戻り値は各ステージの結果 dict
    """
    mode = getattr(settings, "ss_cluster_mode", "off")
    logger.info(
        "run_video_analysis_pipeline: video_id=%s mode=%s ray_live=%s",
        video_id, mode, _ray_live(),
    )

    # ステージ1: TrackNet と MediaPipe を並列 (Ray 時) / 逐次 (非 Ray 時)
    tracknet_ref = _call(_tasks.run_tracknet, video_path)
    mediapipe_ref = _call(_tasks.run_mediapipe, video_path)

    tracknet_result = _get(tracknet_ref)
    mediapipe_result = _get(mediapipe_ref)

    # ステージ2: クリップ抽出 (TrackNet の結果を利用)
    rally_bounds = None
    if isinstance(tracknet_result, dict):
        rally_bounds = tracknet_result.get("rally_bounds")
    clips_result = _get(_call(_tasks.extract_clips, video_path, rally_bounds))

    # ステージ3: 統計 / 重心 / ショット分類 を並列
    stats_ref = _call(_tasks.run_statistics, video_id)
    cog_ref = _call(_tasks.calc_center_of_gravity, video_id)
    shots_ref = _call(_tasks.classify_shots, video_id)

    return {
        "video_id": video_id,
        "mode": mode,
        "ray": _ray_live(),
        "tracknet": tracknet_result,
        "mediapipe": mediapipe_result,
        "clips": clips_result,
        "statistics": _get(stats_ref),
        "center_of_gravity": _get(cog_ref),
        "shots": _get(shots_ref),
    }
