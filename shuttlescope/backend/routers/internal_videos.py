"""R-3: Worker 専用の動画ストリーミング API (予備実装)。

主用途:
  Worker PC が現地に持ち込めない場合の、リモート Worker (クラウド等) からの
  動画取得。HTTP Range 対応で、CV/YOLO 解析時の seek もサポート。

セキュリティ:
  - X-Worker-Token ヘッダで認証 (HMAC 比較、timing-safe)
  - SS_WORKER_AUTH_TOKEN が未設定なら全エンドポイント 503
  - フロント / 一般ユーザは絶対に到達できない (`/api/_internal/...` パス)
  - OpenAPI / Swagger 非公開 (include_in_schema=False)

エンドポイント:
  GET  /api/_internal/videos/server_artifacts          ServerVideoArtifact 一覧
  GET  /api/_internal/videos/server_artifacts/{id}/stream  動画 stream (Range 対応)
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.worker_auth import is_worker_enabled, verify_worker_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["internal-videos"], include_in_schema=False)

_CHUNK = 1024 * 1024  # 1 MB

# G-3: Worker IP 単位レート制限 (in-memory、60 req/分)
import time as _time
from threading import Lock as _Lock
_WORKER_RATE: dict[str, list[float]] = {}
_WORKER_LOCK = _Lock()
_WORKER_RATE_MAX = 60
_WORKER_RATE_WINDOW = 60.0


def _worker_rate_check(ip: str):
    now = _time.time()
    cutoff = now - _WORKER_RATE_WINDOW
    with _WORKER_LOCK:
        history = [t for t in _WORKER_RATE.get(ip, []) if t >= cutoff]
        if len(history) >= _WORKER_RATE_MAX:
            _WORKER_RATE[ip] = history
            raise HTTPException(status_code=429, detail="Worker rate limit exceeded")
        history.append(now)
        _WORKER_RATE[ip] = history


def _require_worker(x_worker_token: Optional[str], request: Optional[Request] = None):
    if not is_worker_enabled():
        raise HTTPException(status_code=503, detail="Worker 機能は無効です (SS_WORKER_AUTH_TOKEN 未設定)")
    if not verify_worker_token(x_worker_token):
        raise HTTPException(status_code=401, detail="Worker トークンが無効です")
    if request is not None:
        ip = (
            request.headers.get("CF-Connecting-IP")
            or (request.client.host if request.client else "")
        )[:64]
        _worker_rate_check(ip or "unknown")


def _parse_range(header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    if not header or not header.startswith("bytes="):
        return None
    try:
        spec = header[len("bytes="):]
        a, _, b = spec.partition("-")
        start = int(a) if a else 0
        end = int(b) if b else file_size - 1
        if start < 0 or end >= file_size or start > end:
            return None
        return start, end
    except (ValueError, TypeError):
        return None


def _file_iter(path: Path, start: int, end: int):
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/_internal/videos/server_artifacts")
def list_artifacts(
    request: Request,
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    db: Session = Depends(get_db),
    limit: int = 100,
    match_id: Optional[int] = None,
    unsynced_only: bool = False,
):
    """Worker 向け: 録画アーティファクト一覧。CV 解析対象の検出に使う。"""
    _require_worker(x_worker_token, request)
    if limit > 500:
        limit = 500
    from backend.db.models import ServerVideoArtifact
    q = db.query(ServerVideoArtifact)
    if match_id is not None:
        q = q.filter(ServerVideoArtifact.match_id == match_id)
    if unsynced_only:
        q = q.filter(ServerVideoArtifact.worker_synced_at.is_(None))
    rows = q.order_by(ServerVideoArtifact.id.desc()).limit(limit).all()
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "match_id": r.match_id,
                "upload_id": r.upload_id,
                "file_size_bytes": r.file_size_bytes,
                "mime_type": r.mime_type,
                "duration_seconds": r.duration_seconds,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
                "worker_synced_at": r.worker_synced_at.isoformat() if r.worker_synced_at else None,
            }
            for r in rows
        ],
    }


@router.get("/_internal/videos/server_artifacts/{artifact_id}/stream")
def stream_artifact(
    request: Request,
    artifact_id: int = PathParam(..., ge=1, le=2_147_483_647),
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    db: Session = Depends(get_db),
):
    """Worker 向け: 録画ファイル stream (Range 対応)。

    path_jail で許可ルート外のパスは拒否される。
    """
    _require_worker(x_worker_token, request)
    from backend.db.models import ServerVideoArtifact
    art = db.get(ServerVideoArtifact, artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="アーティファクトが見つかりません")

    path = Path(art.file_path)
    # path_jail で許可ルート確認
    from backend.utils.path_jail import is_allowed_video_path
    if not path.exists() or not path.is_file() or not is_allowed_video_path(path):
        raise HTTPException(status_code=404, detail="ファイルが見つからないか許可外です")

    file_size = path.stat().st_size
    suffix = path.suffix.lower()
    content_type = (
        mimetypes.types_map.get(suffix)
        or art.mime_type
        or "application/octet-stream"
    )

    range_spec = _parse_range(request.headers.get("range"), file_size)
    if range_spec is None:
        return StreamingResponse(
            _file_iter(path, 0, file_size - 1),
            status_code=200,
            media_type=content_type,
            headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"},
        )
    start, end = range_spec
    chunk_size = end - start + 1
    return StreamingResponse(
        _file_iter(path, start, end),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Length": str(chunk_size),
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
        },
    )


@router.post("/_internal/videos/server_artifacts/{artifact_id}/mark_synced")
def mark_synced(
    request: Request,
    artifact_id: int = PathParam(..., ge=1, le=2_147_483_647),
    x_worker_token: Optional[str] = Header(None, alias="X-Worker-Token"),
    db: Session = Depends(get_db),
):
    """Worker が同期完了後にこれを叩く。worker_synced_at を更新。"""
    _require_worker(x_worker_token, request)
    from datetime import datetime
    from backend.db.models import ServerVideoArtifact
    art = db.get(ServerVideoArtifact, artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail="アーティファクトが見つかりません")
    art.worker_synced_at = datetime.utcnow()
    db.commit()
    return {"success": True, "data": {"id": artifact_id, "synced_at": art.worker_synced_at.isoformat()}}
