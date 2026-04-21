"""ビデオ解析パイプライン (INFRA Phase D)

Vol.2 §3.3 準拠:
  TrackNet / MediaPipe を並列 → extract_clips → statistics / CoG / shot 分類
Ray 未起動時は同期フォールバック。

クラスタモード時の分散推論:
  - TrackNet: PC1でフレーム前処理 → K10へnumpyバイト送信 → 推論結果を返す
  - 動画ファイルはPC1にしかないため、K10へのvideo_path直接渡しは行わない
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from backend.config import settings

from . import tasks as _tasks
from .bootstrap import is_ray_available

logger = logging.getLogger(__name__)

# TrackNet入出力定数（inference.pyと一致させる）
_TN_INPUT_W, _TN_INPUT_H, _TN_FRAME_STACK = 512, 288, 3
_TN_CHUNK = 64  # 1回のRay呼び出しあたりのウィンドウ数


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


def _get_remote_worker_model_path() -> str | None:
    """cluster.config.yaml からリモートワーカーの tracknet モデルパスを取得する。"""
    try:
        from backend.cluster.topology import load_config, get_primary_ip
        cfg = load_config()
        head_ip = get_primary_ip()
        for w in cfg.get("network", {}).get("workers", []):
            if w.get("ip", "") != head_ip:
                model_base = w.get("model_base", r"C:\ss-models")
                # IR形式優先
                xml = model_base + r"\tracknet.xml"
                onnx = model_base + r"\tracknet.onnx"
                return xml  # K10上のパスなのでos.path.existsは不可
    except Exception:
        pass
    return None


def _run_tracknet_distributed(video_path: str) -> Dict[str, Any]:
    """PC1でフレーム前処理、K10でTrackNet推論する分散実行。

    K10はbackend/cvモジュールを持たず動画ファイルへのアクセスもないため、
    PC1が前処理済みnumpyバイトをRay経由でK10に送信し推論結果を回収する。
    """
    try:
        import cv2
        import numpy as np
        import ray  # type: ignore
        from backend.cluster.remote_tasks import _infer_tracknet_frames
        from backend.tracknet.zone_mapper import heatmap_to_zone

        model_path = _get_remote_worker_model_path()
        if model_path is None:
            return {"status": "skipped", "reason": "リモートワーカー設定なし"}

        # ── フレーム前処理（PC1上）──────────────────────────────────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"status": "error", "error": f"動画を開けません: {video_path}"}

        fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
        raw_frames: List[np.ndarray] = []
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            resized = cv2.resize(frame, (_TN_INPUT_W, _TN_INPUT_H))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            raw_frames.append(gray)
        cap.release()

        n_frames = len(raw_frames)
        if n_frames < _TN_FRAME_STACK:
            return {"status": "error", "error": f"フレーム数不足: {n_frames}"}

        # ── チャンクに分割して Ray 経由で K10 へ並列送信 ────────────────────
        remote_infer = ray.remote(_infer_tracknet_frames)
        futures: List[tuple[int, Any]] = []

        for chunk_start in range(0, n_frames - _TN_FRAME_STACK + 1, _TN_CHUNK):
            chunk_end = min(chunk_start + _TN_CHUNK, n_frames - _TN_FRAME_STACK + 1)
            batch = np.stack(
                [
                    np.stack(
                        [raw_frames[i + j] for j in range(_TN_FRAME_STACK)], axis=0
                    )
                    for i in range(chunk_start, chunk_end)
                ],
                axis=0,
            ).astype(np.float32)  # (N, 3, H, W)

            header = np.array(batch.shape, dtype=np.int32).tobytes()
            future = remote_infer.remote(
                model_path=model_path, frames_npy=header + batch.tobytes()
            )
            futures.append((chunk_start, future))

        # ── 結果回収・デシリアライズ ─────────────────────────────────────────
        samples: List[Dict[str, Any]] = []
        for chunk_start, future in futures:
            try:
                result_bytes: bytes = ray.get(future, timeout=120)
            except Exception as exc:
                logger.warning("K10推論タイムアウト chunk_start=%d: %s", chunk_start, exc)
                continue

            # JSON エラーレスポンスか確認
            try:
                err_obj = json.loads(result_bytes)
                if "error" in err_obj:
                    logger.warning("K10推論エラー chunk=%d: %s", chunk_start, err_obj["error"])
                    continue
            except Exception:
                pass  # バイナリデータなので正常

            # 出力デシリアライズ: 先頭12バイトが shape (N,H,W) の int32x3
            shape_arr = np.frombuffer(result_bytes[:12], dtype=np.int32)
            n_out, h_out, w_out = int(shape_arr[0]), int(shape_arr[1]), int(shape_arr[2])
            heatmaps = np.frombuffer(result_bytes[12:], dtype=np.float32).reshape(
                n_out, h_out, w_out
            )

            for i in range(n_out):
                frame_idx = chunk_start + i + 1  # 中央フレームのインデックス
                zone, conf, coords = heatmap_to_zone(heatmaps[i])
                samples.append(
                    {
                        "frame_idx": frame_idx,
                        "zone": zone,
                        "confidence": round(conf, 3),
                        "x_norm": round(coords[0], 4) if coords else None,
                        "y_norm": round(coords[1], 4) if coords else None,
                    }
                )

        return {
            "status": "ok",
            "backend": "distributed_k10",
            "sample_count": len(samples),
            "samples": samples,
            "rally_bounds": None,
        }

    except Exception as exc:
        logger.warning("_run_tracknet_distributed 失敗: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}


def _run_tracknet_local(video_path: str) -> Dict[str, Any]:
    """ローカル（PC1）で TrackNet を実行する。Ray に送らない。"""
    from backend.cluster.tasks import _safe_call
    return _safe_call("backend.cv.tracknet_runner", "run_tracknet", video_path)


def run_video_analysis_pipeline(video_id: int, video_path: str) -> Dict[str, Any]:
    """動画解析パイプラインのエントリポイント。

    クラスタモード (ray) かつ Ray 起動済みなら K10 で分散 TrackNet 推論。
    それ以外は同一プロセスで逐次実行 (フォールバック)。
    """
    mode = getattr(settings, "ss_cluster_mode", "off")
    use_distributed = (mode == "ray" and _ray_live())
    logger.info(
        "run_video_analysis_pipeline: video_id=%s mode=%s ray_live=%s distributed=%s",
        video_id, mode, _ray_live(), use_distributed,
    )

    # ── ステージ1: TrackNet ──────────────────────────────────────────────────
    # 動画ファイルはPC1にしかないため、クラスタ時は前処理をPC1で行い
    # フレームバイトだけをK10へ送る分散方式を使う
    if use_distributed:
        tracknet_result = _run_tracknet_distributed(video_path)
        if tracknet_result.get("status") == "error":
            logger.warning("分散TrackNet失敗、ローカルにフォールバック: %s", tracknet_result.get("error"))
            tracknet_result = _run_tracknet_local(video_path)
    else:
        tracknet_result = _run_tracknet_local(video_path)

    # ── ステージ1: MediaPipe（常にPC1ローカル実行）─────────────────────────
    # Pose も動画ファイルが必要なためK10への直接送信は不可
    mediapipe_result = _get(_call(_tasks.run_mediapipe, video_path))

    # ── ステージ2: クリップ抽出 ──────────────────────────────────────────────
    rally_bounds = None
    if isinstance(tracknet_result, dict):
        rally_bounds = tracknet_result.get("rally_bounds")
    clips_result = _get(_call(_tasks.extract_clips, video_path, rally_bounds))

    # ── ステージ3: 統計 / 重心 / ショット分類 ───────────────────────────────
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
