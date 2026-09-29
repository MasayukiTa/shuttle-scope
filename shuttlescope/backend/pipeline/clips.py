"""クリップ抽出モジュール。

ラリー境界リストをもとに ffmpeg でクリップを切り出す。

エンコーダ優先順位（SS_USE_GPU=1 時）:
  1. h264_nvenc  — NVIDIA GPU (NVDEC decode + NVENC encode)
  2. h264_qsv    — Intel Quick Sync Video (QSV decode + encode)
  3. libx264     — CPU フォールバック

並列処理:
  SS_CLIP_WORKERS   — 並列 ffmpeg プロセス数 (0=自動)
  SS_CLIP_FFMPEG_THREADS — ffmpeg 内部スレッド数/プロセス (0=自動)
  自動計算: workers = max(1, cpu_count - 2), ff_threads = cpu_count // workers

seek 戦略（精度と速度の両立）:
  -ss [start - PRE_SEEK_SEC] -i  →  fast seek (keyframe 単位)
  -ss PRE_SEEK_SEC -t duration   →  そこから frame-accurate decode
  PRE_SEEK_SEC=2.0 で最大 2 秒分の余分な decode で精度を担保。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_PRE_SEEK_SEC = 2.0  # fast seek の余裕秒数

# --- HW エンコーダ検出キャッシュ ---
_nvenc_available: Optional[bool] = None
_qsv_available: Optional[bool] = None


def _check_encoder(name: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        r = subprocess.run([ffmpeg, "-encoders"], capture_output=True, text=True, timeout=10)
        return name in r.stdout
    except Exception:
        return False


def _check_nvenc() -> bool:
    global _nvenc_available
    if _nvenc_available is None:
        # nvidia-smi が存在しない = NVIDIA GPU なし → ffmpeg が NVENC を持っていても使えない
        if not shutil.which("nvidia-smi"):
            _nvenc_available = False
            logger.info("[clips] NVENC: False (nvidia-smi not found)")
            return False
        _nvenc_available = _check_encoder("h264_nvenc")
        logger.info("[clips] NVENC: %s", _nvenc_available)
    return _nvenc_available


def _check_qsv() -> bool:
    global _qsv_available
    if _qsv_available is None:
        _qsv_available = _check_encoder("h264_qsv")
        logger.info("[clips] QSV: %s", _qsv_available)
    return _qsv_available


def _use_gpu() -> bool:
    try:
        from backend.config import settings
        return bool(int(getattr(settings, "ss_use_gpu", 0)))
    except Exception:
        return bool(int(os.environ.get("SS_USE_GPU", "0")))


def _video_encoder() -> Tuple[str, List[str], List[str]]:
    """(encoder, hwaccel_input_args, encoder_extra_args) を返す。

    hwaccel_input_args は -i の直前に挿入する。
    encoder_extra_args は -c:v encoder の直後に挿入する。
    """
    if _use_gpu():
        if _check_nvenc():
            return (
                "h264_nvenc",
                ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"],
                ["-preset", "p1", "-rc", "constqp", "-qp", "23"],
            )
        if _check_qsv():
            return (
                "h264_qsv",
                ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv", "-c:v", "h264_qsv"],
                ["-preset", "veryfast"],
            )
    return "libx264", [], ["-preset", "veryfast", "-crf", "23"]


def _clip_concurrency(encoder: str) -> Tuple[int, int]:
    """(workers, ffmpeg_threads_per_worker) を返す。

    エンコーダ種別によってff_threadsを変える:
      NVENC/QSV: エンコードがGPUに移り、CPUの律速は decode/seek/IO に寄る。
                 ff_threads を増やすと並列プロセス間でCPU取り合いが起きスケール低下。
                 → デフォルト ff_threads=1 (最大2まで)
      libx264:   CPUエンコードなのでスレッドを使う価値がある。
                 → デフォルト ff_threads = min(4, usable // workers)、最小2

    workers のデフォルトは4 (I/O 競合の安全起点)。
    SSD でも6本同時 seek+decode は帯域を食うため、
    実測で 3→4→5→6 と上げて p95 レイテンシを確認してから調整すること。

    手動設定: SS_CLIP_WORKERS / SS_CLIP_FFMPEG_THREADS (または config) で上書き可能。
    """
    try:
        from backend.config import settings
        cfg_workers = int(getattr(settings, "ss_clip_workers", 0))
        cfg_threads = int(getattr(settings, "ss_clip_ffmpeg_threads", 0))
    except Exception:
        cfg_workers = int(os.environ.get("SS_CLIP_WORKERS", "0"))
        cfg_threads = int(os.environ.get("SS_CLIP_FFMPEG_THREADS", "0"))

    cpu = os.cpu_count() or 4
    usable = max(1, cpu - 2)  # OS + pipeline worker 側に 2 コア残す

    workers = cfg_workers if cfg_workers > 0 else min(usable, 4)

    if cfg_threads > 0:
        ff_threads = cfg_threads
    elif encoder in ("h264_nvenc", "h264_qsv"):
        ff_threads = 1  # GPU encode: CPU は decode/seek/IO のみ → thread競合を避ける
    else:
        # libx264: workers × ff_threads が usable を超えないよう、最小2・最大4
        ff_threads = min(4, max(2, usable // workers))

    return workers, ff_threads


def _build_cmd(
    ffmpeg: str,
    src: Path,
    start: float,
    duration: float,
    out_path: Path,
    encoder: str,
    hw_args: List[str],
    enc_args: List[str],
    ff_threads: int,
) -> List[str]:
    """ffmpeg コマンドを構築する。

    seek 戦略 (double-seek):
      -ss [start - PRE_SEEK_SEC]  →  fast seek (keyframe 単位、ファイルシーク)
      -i src
      -ss PRE_SEEK_SEC            →  frame-accurate decode (最大 PRE_SEEK_SEC 秒分)
      -t duration

    start < PRE_SEEK_SEC の場合 (例: start=1.0):
      pre_seek=0 → fast seek なし (-ss 0 は冒頭から)
      inner_seek=start → 冒頭からの frame-accurate seek になり正確。
      性能上の問題はない (冒頭付近なので decode コストは小)。

    注意: 出力クリップ先頭のフレームずれは実測で検証すること。
    fast seek の精度は GOP 間隔（通常 1〜2 秒）に依存する。
    """
    pre_seek = max(0.0, start - _PRE_SEEK_SEC)
    inner_seek = start - pre_seek  # 0.0 〜 PRE_SEEK_SEC

    cmd = [ffmpeg, "-y"]
    if pre_seek > 0:
        cmd += ["-ss", f"{pre_seek:.3f}"]
    cmd += hw_args
    cmd += ["-i", str(src)]
    if inner_seek > 0:
        cmd += ["-ss", f"{inner_seek:.3f}"]
    cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-c:v", encoder] + enc_args
    cmd += ["-c:a", "aac"]
    cmd += ["-threads", str(ff_threads)]
    cmd += ["-movflags", "+faststart"]
    cmd += [str(out_path)]
    return cmd


def _run_one(args: Dict[str, Any]) -> Dict[str, Any]:
    """スレッドプール内で1クリップを処理する。成功時は clip dict、失敗時は error dict。"""
    cmd: List[str] = args["cmd"]
    rally_id: int = args["rally_id"]
    out_path: str = args["out_path"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        return {"rally_id": rally_id, "path": out_path}
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"")[-1000:]
        logger.warning("[clips] rally_%d 失敗: %s", rally_id, stderr)
        return {"rally_id": rally_id, "error": str(exc)}
    except Exception as exc:
        logger.warning("[clips] rally_%d 失敗: %s", rally_id, exc)
        return {"rally_id": rally_id, "error": str(exc)}


def extract_clips(
    video_path: str,
    rally_bounds: Optional[List[Dict[str, Any]]] = None,
    output_dir: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """ラリー境界に従ってクリップを並列切り出しする。

    Args:
        video_path: 元動画のパス
        rally_bounds: [{"start_sec": float, "end_sec": float, "rally_id": int}, ...] 形式
                      None の場合はスキップ
        output_dir: 出力ディレクトリ（省略時は動画と同じディレクトリに clips/）

    Returns:
        {"status": "ok"|"skipped"|"error", "encoder": str, "clips": [...]}
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

    encoder, hw_args, enc_args = _video_encoder()
    workers, ff_threads = _clip_concurrency(encoder)
    logger.info("[clips] encoder=%s workers=%d ff_threads=%d", encoder, workers, ff_threads)

    # ジョブリスト構築
    jobs: List[Dict[str, Any]] = []
    for rb in rally_bounds:
        start = float(rb.get("start_sec", 0))
        end = float(rb.get("end_sec", start + 30))
        rally_id = rb.get("rally_id", 0)
        duration = end - start
        if duration <= 0:
            continue
        out_path = out_dir / f"rally_{rally_id:04d}.mp4"
        cmd = _build_cmd(ffmpeg, src, start, duration, out_path, encoder, hw_args, enc_args, ff_threads)
        jobs.append({"cmd": cmd, "rally_id": rally_id, "out_path": str(out_path)})

    if not jobs:
        return {"status": "ok", "encoder": encoder, "clips": []}

    # 並列実行
    clips: List[Dict[str, Any]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run_one, j): j["rally_id"] for j in jobs}
        for fut in as_completed(futures):
            result = fut.result()
            if "error" in result:
                errors += 1
            else:
                clips.append(result)

    # rally_id 順にソート
    clips.sort(key=lambda c: c["rally_id"])
    logger.info("[clips] %d / %d 完了, %d 失敗 (encoder=%s)", len(clips), len(jobs), errors, encoder)
    return {"status": "ok", "encoder": encoder, "clips": clips}
