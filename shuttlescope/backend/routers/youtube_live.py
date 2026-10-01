"""YouTube Live 録画 API ルーター。"""
from __future__ import annotations

import ipaddress
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match
from backend.utils.auth import get_auth, user_can_access_match

logger = logging.getLogger(__name__)
router = APIRouter(tags=["youtube_live"])


def _require_auth(request: Request):
    """録画 job の操作・閲覧は運用ロールに限る。

    `_job_status` は `out_path` (サーバの絶対パス) と元 URL を返す。
    旧実装は「ロールが何かある」だけで通していたので、公開登録で作った
    player アカウントでも全 job の一覧とサーバのパスが読めていた。
    録画はオペレーション機能なので player / llm / demo には開けない。
    """
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    if ctx.role not in ("admin", "analyst", "coach"):
        raise HTTPException(status_code=403, detail="この操作の権限がありません")
    return ctx


def _can_access_job(ctx, job) -> bool:
    """Admin or same-team owner may inspect/mutate a live-recording job.

    Jobs are process-local and may contain absolute server paths and an active
    recorder process, so job_id is never treated as an authorization proof.
    Users without a team fall back to exact user ownership.
    """
    if ctx.is_admin:
        return True
    owner_team_id = getattr(job, "owner_team_id", None)
    owner_user_id = getattr(job, "owner_user_id", None)
    if ctx.team_id is not None and owner_team_id is not None:
        return int(ctx.team_id) == int(owner_team_id)
    return (
        ctx.user_id is not None
        and owner_user_id is not None
        and int(ctx.user_id) == int(owner_user_id)
    )


def _visible_job_or_404(request: Request, job_id: str):
    from backend.services.youtube_live_recorder import get_job

    ctx = _require_auth(request)
    job = get_job(job_id)
    if job is None or not _can_access_job(ctx, job):
        raise HTTPException(status_code=404, detail="job が見つかりません")
    return job


def _validate_public_https_url(value: str) -> str:
    """Pydantic field_validator + create_drm_job 防御層で共有する URL 検証。

    SSRF / scheme 混在 / embedded creds / 内部 IP / 制御文字を Pydantic 層で reject。
    `services/youtube_live_recorder.py::_validate_url_for_subprocess` と同等の
    判定を入口側 (Router StartRequest) にも入れて、HLS probe を bypass して
    DRM フォールバックに落ちる経路でも生 URL が `RecordJob.url` に格納されない
    ようにする (round156 R156-S1 対策)。
    """
    s = (value or "").strip()
    # 制御文字 / 改行 / DEL を拒否
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in s):
        raise ValueError("url contains control character")
    try:
        parsed = urlparse(s)
    except Exception as exc:  # urlparse は基本失敗しないが念のため
        raise ValueError(f"url parse failed: {exc}")
    # scheme allowlist: https のみ (http / ftp / javascript / data / file 等を排除)
    if parsed.scheme != "https":
        raise ValueError("url must use https://")
    # embedded credentials を拒否
    if parsed.username or parsed.password:
        raise ValueError("url must not contain embedded credentials")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError("url has no host")
    if host in ("localhost", "localhost.localdomain", "ip6-localhost"):
        raise ValueError(f"url host {host!r} is not allowed")
    # IP 直指定なら loopback / private / link-local / reserved / multicast を弾く
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # ホスト名 (DNS 解決対象) — 入口層では弾かない
        # ※ DNS rebinding 対策は subprocess 実行直前で別途実施
        pass
    else:
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"url host {host!r} is internal/reserved IP")
    return s


class StartRequest(BaseModel):
    # mass-assignment 防御: schema に無いフィールド (archive_dir 等) は 422 で拒否。
    # R271 attack で archive_dir が silent ignore されていたため明示化。
    model_config = {"extra": "forbid"}
    url: str = Field(..., min_length=10, max_length=500)
    quality: str = Field("best", pattern=r"^(best|1080p|720p|480p|360p)$")
    # 認証あり配信用: ブラウザ名 ("chrome","firefox","edge","brave") またはクッキーファイルパス
    cookie_browser: Optional[str] = Field(None, pattern=r"^(chrome|firefox|edge|brave|opera|vivaldi|safari)$")
    cookie_file: Optional[str] = Field(None, max_length=500)

    @field_validator("cookie_file")
    @classmethod
    def _validate_cookie_file_path(cls, v: Optional[str]) -> Optional[str]:
        # Round 258 R29 P3 fix (R29 P3-2): cookie_file は max_length しか検証されておらず、
        # 任意 path (e.g. `/etc/shadow`, `C:\\Windows\\System32\\config\\SAM`) を渡されても
        # yt-dlp に転送されてファイル存在 / parse error が stderr に leak していた。
        # 修正: 許可 root (`SS_COOKIE_DIR` または `./cookies/`) 直下のファイルだけに限定。
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        import os as _os_cf, pathlib as _pl_cf
        cookies_root_str = _os_cf.environ.get("SS_COOKIE_DIR") or "./cookies"
        try:
            root = _pl_cf.Path(cookies_root_str).resolve(strict=False)
            target = _pl_cf.Path(v).resolve(strict=False)
            target.relative_to(root)
        except (ValueError, OSError) as exc:
            raise ValueError(f"cookie_file は {cookies_root_str} 配下のファイルのみ許可されます: {exc}")
        return str(target)
    # 紐付け試合 ID（指定するとアーカイブ完了時に Match.video_local_path が自動更新される）
    match_id: Optional[int] = Field(None, ge=1, le=2_147_483_647)

    @field_validator("url")
    @classmethod
    def _ensure_safe_url(cls, v: str) -> str:
        return _validate_public_https_url(v)


def _job_status(job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "method": job.method,
        "file_size": job.file_size(),
        "elapsed": job.elapsed(),
        "error": job.error,
        "out_path": str(job.out_path),
        # HDCP / 黒フレーム検出時の警告 (post-stop / 既定 None)
        "warning": getattr(job, "warning", None),
    }


@router.post("/youtube_live/start")
def start_recording(
    body: StartRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """録画を開始する。HLS プローブ後に method を確定して返す。

    Returns:
        method="hls"          → バックエンドで ffmpeg 録画中
        method="drm_required" → Electron desktopCapturer fallback が必要
    """
    ctx = _require_auth(request)

    # Match binding is a write-capable side effect: archive completion may update
    # Match.video_local_path. Authorize it before any yt-dlp/ffmpeg/network probe.
    if body.match_id is not None:
        match = db.get(Match, body.match_id)
        if match is None or not user_can_access_match(ctx, match):
            raise HTTPException(status_code=404, detail="Match not found")

    from backend.services.youtube_live_recorder import (
        probe_hls, start_hls_recording, create_drm_job,
    )

    viable = probe_hls(body.url, body.cookie_browser, body.cookie_file)
    owner_kwargs = {
        "owner_user_id": ctx.user_id,
        "owner_team_id": ctx.team_id,
    }
    if viable:
        job = start_hls_recording(
            body.url,
            body.cookie_browser,
            body.cookie_file,
            body.match_id,
            **owner_kwargs,
        )
        return _job_status(job)
    else:
        job = create_drm_job(body.url, body.match_id, **owner_kwargs)
        resp = _job_status(job)
        resp["method"] = "drm_required"
        return resp


@router.post("/youtube_live/{job_id}/chunk")
async def receive_chunk(job_id: str, request: Request):
    """Electron から webm チャンクを受信する（Content-Type: application/octet-stream）。"""
    _visible_job_or_404(request, job_id)
    from backend.services.youtube_live_recorder import receive_drm_chunk

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="chunk body が空です")
    ok = receive_drm_chunk(job_id, body)
    if not ok:
        raise HTTPException(status_code=404, detail="job が見つかりません")
    return {"ok": True}


@router.post("/youtube_live/{job_id}/stop")
def stop_recording(job_id: str, request: Request):
    """録画を停止する。DRM の場合は webm → mp4 remux を実行する。"""
    _visible_job_or_404(request, job_id)
    from backend.services.youtube_live_recorder import stop_recording as _stop

    job = _stop(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job が見つかりません")
    return _job_status(job)


@router.get("/youtube_live/{job_id}/status")
def get_status(job_id: str, request: Request):
    """録画 job のステータスを返す（ポーリング用）。"""
    job = _visible_job_or_404(request, job_id)
    return _job_status(job)


@router.get("/youtube_live/jobs")
def list_jobs(request: Request):
    """全 job の一覧を返す。"""
    ctx = _require_auth(request)
    from backend.services.youtube_live_recorder import list_jobs as _list

    return [_job_status(j) for j in _list() if _can_access_job(ctx, j)]
