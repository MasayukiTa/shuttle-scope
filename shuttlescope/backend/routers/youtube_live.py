"""YouTube Live 録画 API ルーター。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["youtube_live"])


def _require_auth(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return ctx


class StartRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=500)
    quality: str = Field("best", pattern=r"^(best|1080p|720p|480p|360p)$")
    # 認証あり配信用: ブラウザ名 ("chrome","firefox","edge","brave") またはクッキーファイルパス
    cookie_browser: Optional[str] = Field(None, pattern=r"^(chrome|firefox|edge|brave|opera|vivaldi|safari)$")
    cookie_file: Optional[str] = Field(None, max_length=500)


def _job_status(job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "method": job.method,
        "file_size": job.file_size(),
        "elapsed": job.elapsed(),
        "error": job.error,
        "out_path": str(job.out_path),
    }


@router.post("/youtube_live/start")
def start_recording(body: StartRequest, request: Request):
    """録画を開始する。HLS プローブ後に method を確定して返す。

    Returns:
        method="hls"          → バックエンドで ffmpeg 録画中
        method="drm_required" → Electron desktopCapturer fallback が必要
    """
    _require_auth(request)
    from backend.services.youtube_live_recorder import (
        probe_hls, start_hls_recording, create_drm_job,
    )

    viable = probe_hls(body.url, body.cookie_browser, body.cookie_file)
    if viable:
        job = start_hls_recording(body.url, body.cookie_browser, body.cookie_file)
        return _job_status(job)
    else:
        job = create_drm_job(body.url)
        resp = _job_status(job)
        resp["method"] = "drm_required"
        return resp


@router.post("/youtube_live/{job_id}/chunk")
async def receive_chunk(job_id: str, request: Request):
    """Electron から webm チャンクを受信する（Content-Type: application/octet-stream）。"""
    _require_auth(request)
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
    _require_auth(request)
    from backend.services.youtube_live_recorder import stop_recording as _stop

    job = _stop(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job が見つかりません")
    return _job_status(job)


@router.get("/youtube_live/{job_id}/status")
def get_status(job_id: str, request: Request):
    """録画 job のステータスを返す（ポーリング用）。"""
    _require_auth(request)
    from backend.services.youtube_live_recorder import get_job

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job が見つかりません")
    return _job_status(job)


@router.get("/youtube_live/jobs")
def list_jobs(request: Request):
    """全 job の一覧を返す。"""
    _require_auth(request)
    from backend.services.youtube_live_recorder import list_jobs as _list

    return [_job_status(j) for j in _list()]
