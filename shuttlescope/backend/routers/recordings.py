"""録画/動画スロット API。

設計: 試合枠(match)を先に作成 → match_id 確定 → その match の **枝番(branch_no)** に
複数動画(upload/live)を結びつける。録画/upload の制御面。

- POST /api/matches/{match_id}/recordings : 枝番を自動採番してスロット作成 (privileged)
- GET  /api/matches/{match_id}/recordings : 一覧 (枝番順)
- PATCH /api/recordings/{rec_id}          : 状態/パス/解像度等を更新 (privileged。live 録画完了時など)

動画内部パスは露出させず video_token を返す (Match と同方針)。
"""
from __future__ import annotations

from datetime import datetime
import hmac
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi.responses import StreamingResponse

from backend.db.database import get_db
from backend.db.models import Recording
from backend.services.recording_lifecycle import lock_match_for_recording, next_recording_branch_no
from backend.utils.auth import get_auth, require_match_access_or_404

router = APIRouter()

_PRIVILEGED = {"admin", "analyst", "coach"}
_VALID_KIND = {"upload", "live"}
_VALID_STATUS = {"pending", "recording", "ready", "failed"}


def _require_privileged(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if ctx.role not in _PRIVILEGED:
        raise HTTPException(status_code=403, detail="privileged role required")
    return ctx


class RecordingCreate(BaseModel):
    kind: str = Field(default="upload", max_length=20)
    source_kind: Optional[str] = Field(default=None, max_length=20)
    label: Optional[str] = Field(default=None, max_length=100)
    resolution: Optional[str] = Field(default=None, max_length=20)
    fps: Optional[int] = Field(default=None, ge=1, le=1000)


class RecordingPatch(BaseModel):
    status: Optional[str] = Field(default=None, max_length=20)
    video_local_path: Optional[str] = Field(default=None, max_length=500)
    resolution: Optional[str] = Field(default=None, max_length=20)
    fps: Optional[int] = Field(default=None, ge=1, le=1000)
    label: Optional[str] = Field(default=None, max_length=100)
    ended: Optional[bool] = None  # True で ended_at を now に


def _to_dict(r: Recording) -> dict:
    # 内部パス(video_local_path)は露出しない。配信は video_token 経由。
    return {
        "id": r.id,
        "match_id": r.match_id,
        "branch_no": r.branch_no,
        "kind": r.kind,
        "source_kind": r.source_kind,
        "status": r.status,
        "video_token": r.video_token,
        "resolution": r.resolution,
        "fps": r.fps,
        "label": r.label,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "ended_at": r.ended_at.isoformat() if r.ended_at else None,
    }


@router.post("/matches/{match_id}/recordings", status_code=201)
def create_recording(match_id: int, body: RecordingCreate, request: Request, db: Session = Depends(get_db)):
    _require_privileged(request)
    if body.kind not in _VALID_KIND:
        raise HTTPException(status_code=422, detail=f"invalid kind: {body.kind!r}")
    # team 境界を強制 (アクセス不可 match は 404 で隠蔽。IDOR 防止)
    require_match_access_or_404(match_id, request, db)
    # 同じ match の camera finalize と枝番採番を直列化する。
    # PostgreSQL では match row lock が効き、同時作成で branch_no が衝突しない。
    if lock_match_for_recording(db, match_id) is None:
        raise HTTPException(status_code=404, detail="match not found")
    branch_no = next_recording_branch_no(db, match_id)
    rec = Recording(
        match_id=match_id,
        branch_no=branch_no,
        kind=body.kind,
        source_kind=body.source_kind,
        label=body.label,
        resolution=body.resolution,
        fps=body.fps,
        status="recording" if body.kind == "live" else "pending",
        started_at=datetime.utcnow() if body.kind == "live" else None,
        video_token=str(uuid4()),
    )
    db.add(rec)
    db.commit()
    return _to_dict(rec)


@router.get("/matches/{match_id}/recordings")
def list_recordings(match_id: int, request: Request, db: Session = Depends(get_db)):
    # team 境界を強制: アクセス不可 match の video_token を収集されないよう 404 隠蔽。
    require_match_access_or_404(match_id, request, db)
    rows = (
        db.query(Recording)
        .filter(Recording.match_id == match_id)
        .order_by(Recording.branch_no.asc())
        .all()
    )
    return {"success": True, "data": [_to_dict(r) for r in rows]}


@router.patch("/recordings/{rec_id}")
def patch_recording(rec_id: int, body: RecordingPatch, request: Request, db: Session = Depends(get_db)):
    _require_privileged(request)
    rec = db.get(Recording, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")
    # team 境界を強制: 他チームの match に属する recording を更新できないよう 404 隠蔽。
    require_match_access_or_404(rec.match_id, request, db)
    if body.status is not None:
        if body.status not in _VALID_STATUS:
            raise HTTPException(status_code=422, detail=f"invalid status: {body.status!r}")
        rec.status = body.status
    if body.video_local_path is not None:
        rec.video_local_path = body.video_local_path
    if body.resolution is not None:
        rec.resolution = body.resolution
    if body.fps is not None:
        rec.fps = body.fps
    if body.label is not None:
        rec.label = body.label
    if body.ended:
        rec.ended_at = datetime.utcnow()
    db.commit()
    return _to_dict(rec)

def _recording_file_path(recording: Recording) -> Path:
    raw = (recording.video_local_path or "").strip()
    if raw.startswith("server://"):
        # import at request time to avoid router import cycles.
        from backend.routers.uploads import UPLOAD_DIR
        from backend.utils.server_video_ref import resolve_server_video_path
        try:
            _ref, path = resolve_server_video_path(Path(UPLOAD_DIR), raw)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="invalid server video reference") from exc
        return path
    if raw.startswith("localfile:///"):
        from backend.utils.path_jail import normalize_match_local_path, assert_allowed_video_path
        candidate = normalize_match_local_path(raw)
        if candidate is None:
            raise HTTPException(status_code=404, detail="動画パスを解決できません")
        try:
            return assert_allowed_video_path(candidate)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    # RecordingPatch は legacy 上任意文字列を保持し得る。stream 側では生パスを
    # 決して解釈しないことで、既存データを任意ファイル読出しへ昇格させない。
    raise HTTPException(status_code=404, detail="再生可能な録画パスが設定されていません")


@router.get("/recordings/{rec_id}/stream")
def stream_recording(
    rec_id: int,
    request: Request,
    token: Optional[str] = Query(default=None, min_length=16, max_length=64),
    db: Session = Depends(get_db),
):
    """録画枝を Range 対応で個別再生する。"""
    rec = db.get(Recording, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="recording not found")

    if token and rec.video_token and hmac.compare_digest(token, rec.video_token):
        pass
    else:
        ctx = get_auth(request)
        if ctx.role is None:
            raise HTTPException(status_code=401, detail="authentication required")
        require_match_access_or_404(rec.match_id, request, db)

    file = _recording_file_path(rec)
    if not file.exists() or not file.is_file():
        raise HTTPException(status_code=404, detail="動画ファイルが見つかりません")
    # source がブラウザで再生できない codec (iPhone の HEVC など) なら、生成済みの
    # 再生互換版 (H.264) に差し替える。二視点の 2 本目はここを通る。
    if (rec.video_local_path or "").startswith("server://"):
        from backend.routers.uploads import UPLOAD_DIR
        from backend.services.video_variants import playback_variant_file
        from backend.utils.server_video_ref import parse_server_video_ref
        try:
            _ref = parse_server_video_ref(rec.video_local_path or "")
        except ValueError:
            _ref = None
        _play = (
            playback_variant_file(Path(UPLOAD_DIR), _ref.upload_id)
            if _ref is not None else None
        )
        if _play is not None:
            file = _play

    total = file.stat().st_size
    if total <= 0:
        raise HTTPException(status_code=404, detail="動画ファイルが空です")

    range_header = request.headers.get("range") or request.headers.get("Range")
    start, end = 0, total - 1
    status_code = 200
    if range_header and range_header.startswith("bytes="):
        try:
            part = range_header[6:].split(",")[0]
            start_raw, end_raw = part.split("-", 1)
            if start_raw.strip():
                start = int(start_raw)
            if end_raw.strip():
                end = int(end_raw)
            if start < 0 or end >= total or start > end:
                raise ValueError
            status_code = 206
        except ValueError:
            raise HTTPException(status_code=416, detail="Range ヘッダが不正")

    length = end - start + 1

    def iter_file():
        with open(file, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    content_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".m4v": "video/x-m4v",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
    }.get(file.suffix.lower(), "application/octet-stream")
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": content_type,
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(
        iter_file(),
        status_code=status_code,
        headers=headers,
        media_type=content_type,
    )
