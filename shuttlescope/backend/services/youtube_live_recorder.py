"""YouTube Live 録画サービス。

検出戦略（DRM 自動判定）:
  1. yt-dlp -g [--cookies-from-browser X] で HLS URL を取得
  2. ffmpeg で _PROBE_SECS 秒だけ試し録画
  3. 出力が _PROBE_MIN_BYTES 以上 → HLS 方式で続行
  4. 以下 → DRM 保護と判定 → Electron desktopCapturer fallback

アーカイブ:
  録画停止後、SS_LIVE_ARCHIVE_ROOT が設定されていれば
  バックグラウンドで SSD の backend/data/youtube_live/ から
  HDD の archive_root/youtube_live/ へ移動する。
  path_jail により HDD 上の他データへの書き込みは封鎖される。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from backend.utils.path_jail import resolve_within, is_within

logger = logging.getLogger(__name__)

_RECORD_ROOT = Path(__file__).resolve().parent.parent / "data" / "youtube_live"
_PROBE_SECS = 8
_PROBE_MIN_BYTES = 100_000

SUPPORTED_BROWSERS = ("chrome", "firefox", "edge", "brave", "opera", "vivaldi", "safari")


def _validate_url_for_subprocess(url: str) -> str:
    """subprocess に渡す URL を厳格検証 (CodeQL py/command-line-injection 対策).

    yt-dlp/ffmpeg はコマンド末尾の引数を URL として扱うが、`--exec=evil` 等の
    flag-like な文字列を渡されると引数として解釈し任意コマンド実行に至る。
    list-style subprocess + `--` 区切りで shell expansion は防げるが、yt-dlp 自身が
    `--<flag>` を解釈する経路が残るため、URL 自体を http(s):// で始まる形式に制限し、
    ハイフン始まりを排除する (multi-layer defense)。
    """
    if not isinstance(url, str):
        raise ValueError("url must be string")
    s = url.strip()
    if not (s.startswith("http://") or s.startswith("https://")):
        raise ValueError(f"url must start with http:// or https:// : {s[:50]!r}")
    # 制御文字 / 改行を拒否
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in s):
        raise ValueError("url contains control character")
    # 内部 IP / localhost への SSRF を拒否 (round65 で routers/matches.py に追加した防御を本層にも適用)
    try:
        from urllib.parse import urlparse
        import ipaddress as _ipa
        parsed = urlparse(s)
        host = (parsed.hostname or "").strip().lower()
        if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
            raise ValueError(f"url host {host!r} not allowed")
        if host:
            try:
                ip = _ipa.ip_address(host)
                if (ip.is_loopback or ip.is_private or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                    raise ValueError(f"url host {host!r} is internal/reserved IP")
            except ValueError:
                pass  # ホスト名 → public DNS 解決対象
    except ValueError:
        raise
    except Exception:
        raise ValueError("url parse failed")
    return s


def _archive_root() -> Optional[Path]:
    """設定から HDD アーカイブルートを取得する。未設定なら None。"""
    try:
        from backend.config import settings
        val = getattr(settings, "ss_live_archive_root", "").strip()
    except Exception:
        import os
        val = os.environ.get("SS_LIVE_ARCHIVE_ROOT", "").strip()
    return Path(val) if val else None


@dataclass
class RecordJob:
    job_id: str
    url: str
    out_path: Path
    method: str
    status: str
    started_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    match_id: Optional[int] = None  # 紐付け試合 ID（アーカイブ完了時に DB を自動更新）
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
    ytdlp = _ytdlp()
    if not ytdlp:
        return None
    safe_url = _validate_url_for_subprocess(url)
    # CodeQL py/command-line-injection 対策: `--` で残り引数を positional 扱いに固定
    cmd = [ytdlp, "-g", "--no-playlist", "--live-from-start"]
    cmd += _cookie_args(cookie_browser, cookie_file)
    cmd += ["--", safe_url]
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
    ffmpeg = _ffmpeg_bin()
    hls_url = _get_hls_url(url, cookie_browser, cookie_file)
    if not hls_url or not ffmpeg:
        logger.info("[yt_live] probe skip: hls_url=%s ffmpeg=%s", bool(hls_url), bool(ffmpeg))
        return False

    probe_dir = _RECORD_ROOT / "probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_name = f"probe_{uuid.uuid4().hex[:8]}.mp4"
    probe_path = resolve_within(probe_dir / probe_name, _RECORD_ROOT)
    size = 0

    # ffmpeg `-i <url>` の url が `-` 始まりだと flag として誤解釈されうるため弾く
    if not (hls_url.startswith("http://") or hls_url.startswith("https://")):
        logger.warning("[yt_live] probe rejected: hls_url not http(s)")
        return False
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
        logger.warning("[yt_live] probe error: %s", exc)
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
    match_id: Optional[int] = None,
) -> RecordJob:
    job_id = uuid.uuid4().hex
    _RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = resolve_within(_RECORD_ROOT / f"{job_id}.mp4", _RECORD_ROOT)

    if cookie_browser or cookie_file:
        job = _start_ytdlp_recording(job_id, url, out_path, cookie_browser, cookie_file)
    else:
        job = _start_ffmpeg_recording(job_id, url, out_path)
    job.match_id = match_id
    return job


def _start_ffmpeg_recording(job_id: str, url: str, out_path: Path) -> RecordJob:
    hls_url = _get_hls_url(url)
    ffmpeg = _ffmpeg_bin()
    if not hls_url or not ffmpeg:
        job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                        method="hls", status="error",
                        error="yt-dlp または ffmpeg が利用できません")
        _jobs[job_id] = job
        return job
    # ffmpeg `-i <url>` の url 検証 (CodeQL py/command-line-injection 対策)
    if not (hls_url.startswith("http://") or hls_url.startswith("https://")):
        job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                        method="hls", status="error",
                        error="hls_url が http(s):// で始まりません")
        _jobs[job_id] = job
        return job
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-i", hls_url,
         "-c", "copy", "-movflags", "+faststart", str(out_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                    method="hls", status="recording")
    job._proc = proc
    _jobs[job_id] = job
    logger.info("[yt_live] ffmpeg HLS started: job=%s", job_id)
    return job


def _start_ytdlp_recording(
    job_id: str, url: str, out_path: Path,
    cookie_browser: Optional[str], cookie_file: Optional[str],
) -> RecordJob:
    ytdlp = _ytdlp()
    if not ytdlp:
        job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                        method="hls_ytdlp", status="error",
                        error="yt-dlp が利用できません")
        _jobs[job_id] = job
        return job
    safe_url = _validate_url_for_subprocess(url)
    cmd = [ytdlp, "--live-from-start", "--no-playlist",
           "-f", "best", "--merge-output-format", "mp4",
           "-o", str(out_path)]
    cmd += _cookie_args(cookie_browser, cookie_file)
    # CodeQL py/command-line-injection 対策: `--` 区切りで positional 扱いに固定
    cmd += ["--", safe_url]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                    method="hls_ytdlp", status="recording")
    job._proc = proc
    _jobs[job_id] = job
    logger.info("[yt_live] yt-dlp recording started: job=%s cookie_browser=%s",
                job_id, cookie_browser)
    return job


def create_drm_job(url: str, match_id: Optional[int] = None) -> RecordJob:
    job_id = uuid.uuid4().hex
    _RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = resolve_within(_RECORD_ROOT / f"{job_id}.webm", _RECORD_ROOT)
    job = RecordJob(job_id=job_id, url=url, out_path=out_path,
                    method="drm_pending", status="probing", match_id=match_id)
    _jobs[job_id] = job
    logger.info("[yt_live] DRM job created: job=%s match_id=%s", job_id, match_id)
    return job


def receive_drm_chunk(job_id: str, chunk: bytes) -> bool:
    job = _jobs.get(job_id)
    if not job:
        return False
    if not is_within(job.out_path, _RECORD_ROOT):
        logger.error("[yt_live] chunk rejected: path outside record root: %s", job.out_path)
        return False
    if job.method == "drm_pending":
        job.method = "drm"
        job.status = "recording"
    try:
        with open(job.out_path, "ab") as fh:
            fh.write(chunk)
        return True
    except Exception as exc:
        logger.error("[yt_live] chunk write error job=%s: %s", job_id, exc)
        return False


def _remux_webm_to_mp4(job: RecordJob) -> None:
    ffmpeg = _ffmpeg_bin()
    if not ffmpeg or not job.out_path.exists():
        return
    mp4_path = job.out_path.with_suffix(".mp4")
    if not is_within(mp4_path, _RECORD_ROOT):
        logger.error("[yt_live] remux rejected: outside record root")
        return
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


def _path_to_localfile_url(p: Path) -> str:
    """ファイルパスを localfile:/// 形式の URL に変換する（DB 保存形式）。"""
    return "localfile:///" + str(p).replace("\\", "/")


def _update_match_video_path(old_path: Path, new_path: Path, match_id: Optional[int]) -> int:
    """SSD パスから HDD パスへ Match.video_local_path を更新する。

    更新ターゲット:
      1. job に紐付けられた match_id（指定されていれば）
      2. video_local_path が old_path / old_url と一致する全 Match
         （ユーザーが job 開始後に手動で紐付けた場合に対応）

    返り値: 更新された行数。
    """
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import Match
    except Exception as exc:
        logger.error("[yt_live] DB import failed for archive update: %s", exc)
        return 0

    old_url = _path_to_localfile_url(old_path)
    old_str = str(old_path)
    new_url = _path_to_localfile_url(new_path)

    n = 0
    with SessionLocal() as db:
        # 1. match_id 指定の場合は明示更新（古いパスと一致しなくても）
        if match_id is not None:
            m = db.get(Match, match_id)
            if m is not None and (m.video_local_path or "") != new_url:
                m.video_local_path = new_url
                n += 1
                logger.info("[yt_live] DB updated: match_id=%s → %s", match_id, new_url)
        # 2. 古いパスと一致するレコードを全て更新
        n += (
            db.query(Match)
            .filter(Match.video_local_path.in_([old_url, old_str]))
            .update({"video_local_path": new_url}, synchronize_session=False)
        )
        db.commit()
    return n


def _archive_async(job: RecordJob, archive_root: Path) -> None:
    """SSD 上の録画ファイルを HDD アーカイブルート内の youtube_live/ へ移動する。

    保証:
      - path_jail により archive_root 以外への書き込みは構造上不可能
      - 移動完了時に Match.video_local_path を新パスに自動更新
      - status 遷移: "archiving" → "stopped"（最終状態）
      - 失敗時: SSD 上にファイルが残り、status="stopped" でリトライ可能
    """
    if not job.out_path.exists():
        logger.warning("[yt_live] archive skip: file not found: %s", job.out_path)
        job.status = "stopped"
        return

    dest_dir = archive_root / "youtube_live"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / job.out_path.name

    # path_jail の二重確認（dest が archive_root 内に収まることを保証）
    try:
        resolve_within(dest, archive_root)
    except ValueError as exc:
        logger.error("[yt_live] archive blocked by path_jail: %s", exc)
        job.status = "stopped"
        job.error = f"archive blocked: {exc}"
        return

    old_path = job.out_path
    logger.info("[yt_live] archiving: %s → %s", old_path.name, dest)
    try:
        shutil.move(str(old_path), str(dest))
        job.out_path = dest
        # DB の Match.video_local_path を自動更新（旧 SSD パス → 新 HDD パス）
        try:
            updated = _update_match_video_path(old_path, dest, job.match_id)
            if updated:
                logger.info("[yt_live] match link updated: %d row(s)", updated)
        except Exception as exc:
            logger.error("[yt_live] DB update failed (file already moved): %s", exc)
            job.error = f"archive ok but DB update failed: {exc}"
        job.status = "stopped"
        logger.info("[yt_live] archived ok: job=%s size=%d", job.job_id, job.file_size())
    except Exception as exc:
        logger.error("[yt_live] archive move failed: %s", exc)
        job.status = "stopped"
        job.error = f"archive failed: {exc}"


def stop_recording(job_id: str) -> Optional[RecordJob]:
    """録画停止 → DRM remux → HDD アーカイブ（非同期）。"""
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

    archive = _archive_root()
    if archive:
        # フェイルセーフ: アーカイブ開始前に "archiving" に遷移させる。
        # フロントが "stopped" を最終状態として扱えるようにするため。
        job.status = "archiving"
        threading.Thread(
            target=_archive_async, args=(job, archive), daemon=True,
        ).start()

    return job
