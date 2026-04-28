"""YouTube Live 録画サービス。

検出戦略（DRM 自動判定）:
  1. yt-dlp -g [--cookies-from-browser X] で HLS URL を取得
  2. ffmpeg で _PROBE_SECS 秒だけ試し録画
  3. 出力が _PROBE_MIN_BYTES 以上 → HLS 方式で続行
  4. 以下 → DRM 保護と判定 → Electron desktopCapturer fallback

HLS 録画（認証なし）:
  ffmpeg -i <hls_url> -c copy -movflags +faststart <output.mp4>
  ※ yt-dlp -g が返す URL はプリサインド済みのため Cookie 不要

HLS 録画（認証あり: cookie_browser 指定時）:
  yt-dlp --live-from-start --cookies-from-browser <browser> -o <output> <url>
  ※ HLS セグメントも Cookie 付きで取得するため yt-dlp に任せる

DRM 録画 (Electron 経由):
  - Electron が MediaRecorder webm チャンクを受け取り、
    POST /api/youtube_live/{job_id}/chunk でバックエンドへ転送
  - stop 時に ffmpeg で webm → mp4 remux
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_RECORD_ROOT = Path(__file__).resolve().parent.parent / "data" / "youtube_live"
_PROBE_SECS = 8
_PROBE_MIN_BYTES = 100_000  # 100 KB 未満 = DRM または取得失敗と判定

# yt-dlp --cookies-from-browser で受け付けるブラウザ名
SUPPORTED_BROWSERS = ("chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari")


@dataclass
class RecordJob:
    job_id: str
    url: str
    out_path: Path
    method: str   # "hls" | "hls_ytdlp" | "drm_pending" | "drm"
    status: str   # "probing" | "recording" | "stopped" | "error"
    started_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False)

    def file_size(self) -> int:
        try:
            return self.out_path.stat().st_size
        except FileNotFoundError:
            return 0

    def elapsed(self) -> float:
        return round(time.time() - self.started_at, 1)


_jobs: Dict[str, RecordJob] = {}


def _ytdlp() -> Optional[str]:
    return shutil.which("yt-dlp")


def _ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


def get_job(job_id: str) -> Optional[RecordJob]:
    return _jobs.get(job_id)


def list_jobs() -> list[RecordJob]:
    return list(_jobs.values())


def _cookie_args(cookie_browser: Optional[str], cookie_file: Optional[str]) -> List[str]:
    """yt-dlp 用のクッキー引数を組み立てる。"""
    if cookie_browser and cookie_browser in SUPPORTED_BROWSERS:
        return ["--cookies-from-browser", cookie_browser]
    if cookie_file:
        return ["--cookies", cookie_file]
    return []


def _get_hls_url(
    url: str,
    cookie_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
) -> Optional[str]:
    """yt-dlp -g で HLS URL を取得。認証ありサービスにはクッキーを渡す。"""
    ytdlp = _ytdlp()
    if not ytdlp:
        return None
    cmd = [ytdlp, "-g", "--no-playlist", "--live-from-start"]
    cmd += _cookie_args(cookie_browser, cookie_file)
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
            return lines[0] if lines else None
        logger.info("[yt_live] yt-dlp -g rc=%d stderr=%s",
                    result.returncode, result.stderr[-300:])
    except Exception as exc:
        logger.warning("[yt_live] yt-dlp -g failed: %s", exc)
    return None


def probe_hls(
    url: str,
    cookie_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
) -> bool:
    """HLS で _PROBE_SECS 秒試し録画し、DRM 非保護かどうかを返す。

    認証ありサービスでも yt-dlp がプリサインド URL を返せば ffmpeg でプローブ可能。
    ffmpeg が 403 などで失敗する場合、サイズ 0 → DRM と同等に扱い Electron fallback に委ねる。
    """
    ffmpeg = _ffmpeg_bin()
    hls_url = _get_hls_url(url, cookie_browser, cookie_file)
    if not hls_url or not ffmpeg:
        logger.info("[yt_live] probe skip: hls_url=%s ffmpeg=%s", bool(hls_url), bool(ffmpeg))
        return False

    probe_dir = _RECORD_ROOT / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_path = probe_dir / f"probe_{uuid.uuid4().hex[:8]}.mp4"
    size = 0

    try:
        proc = subprocess.Popen(
            [ffmpeg, "-y", "-i", hls_url,
             "-t", str(_PROBE_SECS), "-c", "copy", str(probe_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc.wait(timeout=_PROBE_SECS + 20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except Exception as exc:
        logger.warning("[yt_live] probe subprocess error: %s", exc)
    finally:
        size = probe_path.stat().st_size if probe_path.exists() else 0
        probe_path.unlink(missing_ok=True)

    viable = size >= _PROBE_MIN_BYTES
    logger.info("[yt_live] probe: url=%s bytes=%d viable=%s", url[:60], size, viable)
    return viable


def start_hls_recording(
    url: str,
    cookie_browser: Optional[str] = None,
    cookie_file: Optional[str] = None,
) -> RecordJob:
    """HLS 方式で録画を開始する。

    cookie_browser / cookie_file が指定されている場合:
      yt-dlp を直接使って録画する。
      理由: CDN がセグメント配信時にも Cookie を要求するサービス（NHK+、ニコ生等）では
            ffmpeg は HLS URL が取れても 403 になるため、yt-dlp に認証を委ねる。

    指定がない場合:
      yt-dlp -g → HLS URL → ffmpeg -c copy（コピーのみ、再エンコードなし）
    """
    job_id = uuid.uuid4().hex
    _RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = _RECORD_ROOT / f"{job_id}.mp4"

    uses_cookies = bool(cookie_browser or cookie_file)

    if uses_cookies:
        return _start_ytdlp_recording(job_id, url, out_path, cookie_browser, cookie_file)
    else:
        return _start_ffmpeg_recording(job_id, url, out_path)


def _start_ffmpeg_recording(job_id: str, url: str, out_path: Path) -> RecordJob:
    """ffmpeg -c copy で直接 HLS 録画（認証なし用）。"""
    hls_url = _get_hls_url(url)
    ffmpeg = _ffmpeg_bin()

    if not hls_url or not ffmpeg:
        job = RecordJob(
            job_id=job_id, url=url, out_path=out_path,
            method="hls", status="error",
            error="yt-dlp または ffmpeg が利用できません",
        )
        _jobs[job_id] = job
        return job

    proc = subprocess.Popen(
        [ffmpeg, "-y", "-i", hls_url,
         "-c", "copy", "-movflags", "+faststart", str(out_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    job = RecordJob(
        job_id=job_id, url=url, out_path=out_path,
        method="hls", status="recording",
    )
    job._proc = proc
    _jobs[job_id] = job
    logger.info("[yt_live] ffmpeg HLS recording started: job=%s", job_id)
    return job


def _start_ytdlp_recording(
    job_id: str,
    url: str,
    out_path: Path,
    cookie_browser: Optional[str],
    cookie_file: Optional[str],
) -> RecordJob:
    """yt-dlp に直接録画させる（認証あり用）。

    Cookie を yt-dlp が保持したまま HLS セグメントを取得するため、
    CDN がセグメントにも認証を要求するサービスで正しく動作する。
    """
    ytdlp = _ytdlp()
    if not ytdlp:
        job = RecordJob(
            job_id=job_id, url=url, out_path=out_path,
            method="hls_ytdlp", status="error",
            error="yt-dlp が利用できません",
        )
        _jobs[job_id] = job
        return job

    cmd = [
        ytdlp,
        "--live-from-start",
        "--no-playlist",
        "-f", "best",
        "--merge-output-format", "mp4",
        "-o", str(out_path),
    ]
    cmd += _cookie_args(cookie_browser, cookie_file)
    cmd.append(url)

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = RecordJob(
        job_id=job_id, url=url, out_path=out_path,
        method="hls_ytdlp", status="recording",
    )
    job._proc = proc
    _jobs[job_id] = job
    logger.info("[yt_live] yt-dlp recording started: job=%s cookie_browser=%s",
                job_id, cookie_browser)
    return job


def create_drm_job(url: str) -> RecordJob:
    """DRM fallback 用の job を作成する（Electron が chunk を送ってくる前の予約）。"""
    job_id = uuid.uuid4().hex
    _RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = _RECORD_ROOT / f"{job_id}.webm"
    job = RecordJob(
        job_id=job_id, url=url, out_path=out_path,
        method="drm_pending", status="probing",
    )
    _jobs[job_id] = job
    logger.info("[yt_live] DRM job created: job=%s", job_id)
    return job


def receive_drm_chunk(job_id: str, chunk: bytes) -> bool:
    """Electron desktopCapturer の webm チャンクを out_path に追記する。"""
    job = _jobs.get(job_id)
    if not job:
        return False
    if job.method == "drm_pending":
        job.method = "drm"
        job.status = "recording"
        logger.info("[yt_live] DRM recording started: job=%s", job_id)
    try:
        with open(job.out_path, "ab") as fh:
            fh.write(chunk)
        return True
    except Exception as exc:
        logger.error("[yt_live] chunk write error job=%s: %s", job_id, exc)
        return False


def _remux_webm_to_mp4(job: RecordJob) -> None:
    """webm → mp4 remux。成功すれば out_path を更新し webm を削除。"""
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg or not job.out_path.exists():
        return
    mp4_path = job.out_path.with_suffix(".mp4")
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", str(job.out_path), "-c", "copy", str(mp4_path)],
            capture_output=True, timeout=300,
        )
        if result.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 1_000:
            job.out_path.unlink(missing_ok=True)
            job.out_path = mp4_path
            logger.info("[yt_live] remux ok: %s", mp4_path)
        else:
            logger.warning("[yt_live] remux failed rc=%d", result.returncode)
    except Exception as exc:
        logger.error("[yt_live] remux error: %s", exc)


def stop_recording(job_id: str) -> Optional[RecordJob]:
    """録画を停止し、DRM の場合は webm → mp4 remux を行う。"""
    job = _jobs.get(job_id)
    if not job:
        return None

    if job._proc and job._proc.poll() is None:
        job._proc.terminate()
        try:
            job._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            job._proc.kill()

    job.status = "stopped"
    logger.info("[yt_live] stopped: job=%s method=%s size=%d",
                job_id, job.method, job.file_size())

    if job.method == "drm" and job.out_path.suffix == ".webm":
        _remux_webm_to_mp4(job)

    return job
