"""クリップ抽出モジュール（K10 CPU ワーカー向け）。

ラリー境界リストをもとに ffmpeg でクリップを切り出す。
SS_USE_GPU=1 かつ NVENC が利用可能な環境では h264_nvenc に切り替える。
K10 ワーカーでは SS_USE_GPU=0 のため libx264 (CPU エンコード) を使う。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# NVENC が使えるかの検出結果をキャッシュ（プロセス内で1回だけ確認）
_nvenc_available: Optional[bool] = None


def _check_nvenc() -> bool:
    """ffmpeg が NVENC エンコーダを持っているか確認する。"""
    global _nvenc_available
    if _nvenc_available is not None:
        return _nvenc_available

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        _nvenc_available = False
        return False

    try:
        result = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _nvenc_available = "h264_nvenc" in result.stdout
    except Exception:
        _nvenc_available = False

    logger.info("[clips] NVENC 利用可能: %s", _nvenc_available)
    return _nvenc_available


def _video_encoder() -> str:
    """環境に応じてエンコーダ名を返す。"""
    try:
        from backend.config import settings
        use_gpu = int(getattr(settings, "ss_use_gpu", 0))
    except Exception:
        use_gpu = int(os.environ.get("SS_USE_GPU", "0"))

    if use_gpu and _check_nvenc():
        return "h264_nvenc"
    return "libx264"


def extract_clips(
    video_path: str,
    rally_bounds: Optional[List[Dict[str, Any]]] = None,
    output_dir: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """ラリー境界に従ってクリップを切り出す。

    Args:
        video_path: 元動画のパス
        rally_bounds: [{"start_sec": float, "end_sec": float, "rally_id": int}, ...] 形式
                      None の場合はスキップ（ステータス skipped を返す）
        output_dir: 出力ディレクトリ（省略時は動画と同じディレクトリに clips/ を作る）

    Returns:
        {
            "status": "ok" | "skipped" | "error",
            "encoder": str,
            "clips": [{"rally_id": int, "path": str}, ...],
        }
    """
    if rally_bounds is None:
        logger.info("[clips] rally_bounds が None のためスキップ")
        return {"status": "skipped", "reason": "rally_bounds not provided"}

    if not rally_bounds:
        return {"status": "ok", "encoder": "none", "clips": []}

    src = Path(video_path)
    if not src.exists():
        return {"status": "error", "error": f"動画が見つかりません: {video_path}"}

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return {"status": "error", "error": "ffmpeg が見つかりません"}

    out_dir = Path(output_dir) if output_dir else src.parent / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    encoder = _video_encoder()
    clips: List[Dict[str, Any]] = []

    for rb in rally_bounds:
        start = float(rb.get("start_sec", 0))
        end = float(rb.get("end_sec", start + 30))
        rally_id = rb.get("rally_id", 0)
        duration = end - start
        if duration <= 0:
            continue

        out_path = out_dir / f"rally_{rally_id:04d}.mp4"
        cmd = [
            ffmpeg, "-y",
            "-ss", str(start),
            "-i", str(src),
            "-t", str(duration),
            "-c:v", encoder,
            "-c:a", "aac",
            "-movflags", "+faststart",
            str(out_path),
        ]
        # h264_nvenc 向けオプション追加
        if encoder == "h264_nvenc":
            cmd[cmd.index("-c:v") + 2:cmd.index("-c:v") + 2] = [
                "-preset", "p4", "-rc", "vbr", "-b:v", "4M",
            ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
            clips.append({"rally_id": rally_id, "path": str(out_path)})
        except subprocess.CalledProcessError as exc:
            logger.warning("[clips] rally_%d 切り出し失敗: %s", rally_id, exc.stderr)
        except Exception as exc:
            logger.warning("[clips] rally_%d 切り出し失敗: %s", rally_id, exc)

    logger.info("[clips] %d / %d クリップ完了 (encoder=%s)", len(clips), len(rally_bounds), encoder)
    return {"status": "ok", "encoder": encoder, "clips": clips}
