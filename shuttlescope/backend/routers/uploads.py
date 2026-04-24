"""ブラウザからの分割動画アップロード API。

Electron 版はローカル `localfile://` を使うため不要。
Web ブラウザ（iOS Safari 含む）ユーザーが撮影した動画をサーバに保存するための経路。

【大量同時接続時の保護】
- per-user の同時アップロード本数制限（MAX_CONCURRENT_PER_USER）
- グローバル同時チャンク処理セマフォ（MAX_CONCURRENT_CHUNKS）
- ディスク空き容量チェック（MIN_FREE_DISK_BYTES 未満なら init 拒否）
- 最大ファイルサイズ上限（MAX_UPLOAD_SIZE）
- アイドル GC（IDLE_TIMEOUT_SECONDS 以上更新が無い session は .part 削除 + status=expired）

【チャンク受領】
- 受領順不同可。chunk_index × chunk_size の絶対オフセットに pwrite
- 受領状態は bitmap (1bit/chunk) を DB に保持
- 同一 upload_id への同時書き込みは per-upload asyncio.Lock で直列化
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, UploadSession
from backend.utils.auth import AuthCtx, get_auth
from backend.utils.safe_path import safe_path


router = APIRouter(prefix="/v1/uploads", tags=["uploads"])

# ─── 定数 ─────────────────────────────────────────────────────────────────────

UPLOAD_DIR = Path(os.path.abspath("./videos"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_SIZE = 5 * 1024 * 1024 * 1024          # 5GB/ファイル
MIN_CHUNK_SIZE = 64 * 1024                         # 64KB 下限（極端な細分化を防ぐ）
MAX_CHUNK_SIZE = 8 * 1024 * 1024                   # 8MB 上限（Cloudflare 100s タイムアウト余裕）
DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024               # 2MB（クライアントのデフォルト目安）

MAX_CONCURRENT_PER_USER = 2                        # 同一ユーザの並行アップロード本数
MAX_CONCURRENT_CHUNKS = 32                         # サーバ全体で同時に走るチャンク書き込み本数
MIN_FREE_DISK_BYTES = 10 * 1024 * 1024 * 1024      # 空き 10GB 下回ったら init 拒否
IDLE_TIMEOUT_SECONDS = 60 * 60                     # 1 時間チャンク無し → expire
GC_INTERVAL_SECONDS = 5 * 60                       # 5 分おきに GC 実行

ALLOWED_ROLES = {"analyst", "coach", "admin"}

# MIME 許容（空でも許す。ブラウザが種々のバリエーションを返すため寛容）
ALLOWED_MIME_PREFIXES = ("video/",)

# ─── 同時実行制御 ─────────────────────────────────────────────────────────────

# upload_id → asyncio.Lock（同一 upload_id のチャンク書き込みを直列化）
_upload_locks: dict[str, asyncio.Lock] = {}
_upload_locks_guard = asyncio.Lock()

# グローバル同時チャンク数。Semaphore は初期化時のイベントループ確定後に作成する。
_global_chunk_sem: Optional[asyncio.Semaphore] = None


def _get_global_sem() -> asyncio.Semaphore:
    global _global_chunk_sem
    if _global_chunk_sem is None:
        _global_chunk_sem = asyncio.Semaphore(MAX_CONCURRENT_CHUNKS)
    return _global_chunk_sem


async def _get_upload_lock(upload_id: str) -> asyncio.Lock:
    async with _upload_locks_guard:
        lock = _upload_locks.get(upload_id)
        if lock is None:
            lock = asyncio.Lock()
            _upload_locks[upload_id] = lock
        return lock


_UPLOAD_ID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def _part_path(upload_id: str) -> Path:
    if not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=422, detail="無効なアップロードID")
    safe_upload_id = str(uuid.UUID(upload_id))
    return safe_path(UPLOAD_DIR, f"{safe_upload_id}.part")


def _final_path(upload_id: str, filename: str) -> Path:
    if not _UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(status_code=422, detail="無効なアップロードID")
    safe_upload_id = str(uuid.UUID(upload_id))
    ext = Path(filename).suffix.lower() or ".mp4"
    # 拡張子ホワイトリスト（実行可能形式を弾く）
    if ext not in {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg"}:
        ext = ".mp4"
    return safe_path(UPLOAD_DIR, f"{safe_upload_id}{ext}")


def _require_writer(ctx: AuthCtx) -> None:
    if ctx.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="アップロード権限がありません")


def _bitmap_get(bitmap: bytes, idx: int) -> bool:
    byte_i, bit_i = idx // 8, idx % 8
    if byte_i >= len(bitmap):
        return False
    return (bitmap[byte_i] >> bit_i) & 1 == 1


def _bitmap_set(bitmap: bytes, idx: int, total_chunks: int) -> bytes:
    expected = (total_chunks + 7) // 8
    buf = bytearray(bitmap)
    if len(buf) < expected:
        buf.extend(b"\x00" * (expected - len(buf)))
    byte_i, bit_i = idx // 8, idx % 8
    buf[byte_i] |= 1 << bit_i
    return bytes(buf)


def _bitmap_complete(bitmap: bytes, total_chunks: int) -> bool:
    if len(bitmap) * 8 < total_chunks:
        return False
    for i in range(total_chunks):
        if not _bitmap_get(bitmap, i):
            return False
    return True


# ─── スキーマ ─────────────────────────────────────────────────────────────────

class InitRequest(BaseModel):
    match_id: Optional[int] = None
    filename: str
    total_size: int
    chunk_size: int = DEFAULT_CHUNK_SIZE
    mime_type: Optional[str] = None


class InitResponse(BaseModel):
    upload_id: str
    chunk_size: int
    total_chunks: int
    received_indices: list[int] = []


class StatusResponse(BaseModel):
    upload_id: str
    status: str
    received_count: int
    total_chunks: int
    received_indices: list[int]


class FinalizeResponse(BaseModel):
    upload_id: str
    status: str
    final_path: str
    match_id: Optional[int] = None


# ─── エンドポイント ───────────────────────────────────────────────────────────

@router.post("/video/init", response_model=InitResponse)
def init_upload(
    body: InitRequest,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)

    if body.total_size <= 0 or body.total_size > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"ファイルサイズは 1〜{MAX_UPLOAD_SIZE} byte の範囲で指定してください")
    if not (MIN_CHUNK_SIZE <= body.chunk_size <= MAX_CHUNK_SIZE):
        raise HTTPException(status_code=400, detail=f"chunk_size は {MIN_CHUNK_SIZE}〜{MAX_CHUNK_SIZE} byte")
    if body.mime_type and not any(body.mime_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail="動画 MIME タイプのみ許可")
    if body.match_id is not None:
        m = db.get(Match, body.match_id)
        if m is None:
            raise HTTPException(status_code=404, detail="試合が見つかりません")

    # ディスク空き容量チェック
    try:
        free_bytes = shutil.disk_usage(str(UPLOAD_DIR)).free
    except OSError:
        free_bytes = 0
    if free_bytes < max(MIN_FREE_DISK_BYTES, body.total_size * 2):
        raise HTTPException(status_code=507, detail="サーバのディスク空き容量が不足しています")

    # per-user 並列上限チェック
    if ctx.user_id is not None:
        active = db.query(UploadSession).filter(
            UploadSession.user_id == ctx.user_id,
            UploadSession.status == "uploading",
        ).count()
        if active >= MAX_CONCURRENT_PER_USER:
            raise HTTPException(status_code=429, detail=f"同時アップロード本数の上限 ({MAX_CONCURRENT_PER_USER}) に達しています")

    total_chunks = (body.total_size + body.chunk_size - 1) // body.chunk_size
    upload_id = str(uuid.uuid4())
    part = _part_path(upload_id)
    # sparse file 確保。truncate で total_size を確定。
    try:
        with open(part, "wb") as f:
            f.truncate(body.total_size)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f".part ファイル確保に失敗: {e}")

    session = UploadSession(
        id=upload_id,
        user_id=ctx.user_id,
        match_id=body.match_id,
        filename=body.filename[:255],
        mime_type=body.mime_type,
        total_size=body.total_size,
        chunk_size=body.chunk_size,
        total_chunks=total_chunks,
        received_bitmap=b"",
        received_count=0,
        status="uploading",
    )
    db.add(session)
    db.commit()

    return InitResponse(
        upload_id=upload_id,
        chunk_size=body.chunk_size,
        total_chunks=total_chunks,
        received_indices=[],
    )


@router.post("/video/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)

    sem = _get_global_sem()
    async with sem:
        lock = await _get_upload_lock(upload_id)
        async with lock:
            session = db.get(UploadSession, upload_id)
            if session is None:
                raise HTTPException(status_code=404, detail="アップロードセッションが見つかりません")
            if session.status != "uploading":
                raise HTTPException(status_code=409, detail=f"セッションは {session.status} 状態です")
            # 所有者チェック
            if session.user_id is not None and ctx.user_id is not None and session.user_id != ctx.user_id:
                raise HTTPException(status_code=403, detail="このアップロードへの権限がありません")
            if chunk_index < 0 or chunk_index >= session.total_chunks:
                raise HTTPException(status_code=400, detail="chunk_index が範囲外です")

            # 既に受領済みならスキップ（冪等）
            if _bitmap_get(session.received_bitmap, chunk_index):
                return {"success": True, "already_received": True, "received_count": session.received_count}

            # チャンクを読む。最終チャンクは chunk_size 未満でも可
            data = await chunk.read()
            if not data:
                raise HTTPException(status_code=400, detail="空チャンクは拒否")
            expected = session.chunk_size
            is_last = chunk_index == session.total_chunks - 1
            if is_last:
                expected = session.total_size - chunk_index * session.chunk_size
            if len(data) != expected:
                raise HTTPException(status_code=400, detail=f"チャンクサイズ不一致 (expected={expected}, got={len(data)})")

            # 絶対オフセット書き込み（pwrite 相当）。同一 upload_id 内は lock で直列。
            part = _part_path(upload_id)
            offset = chunk_index * session.chunk_size

            def _write() -> None:
                with open(part, "r+b") as f:
                    f.seek(offset)
                    f.write(data)

            await asyncio.get_event_loop().run_in_executor(None, _write)

            session.received_bitmap = _bitmap_set(session.received_bitmap, chunk_index, session.total_chunks)
            session.received_count = session.received_count + 1
            session.updated_at = datetime.utcnow()
            db.commit()

            return {
                "success": True,
                "already_received": False,
                "received_count": session.received_count,
                "total_chunks": session.total_chunks,
            }


@router.get("/video/{upload_id}/status", response_model=StatusResponse)
def upload_status(
    upload_id: str,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)
    session = db.get(UploadSession, upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="アップロードセッションが見つかりません")
    if session.user_id is not None and ctx.user_id is not None and session.user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="このアップロードへの権限がありません")
    received = [i for i in range(session.total_chunks) if _bitmap_get(session.received_bitmap, i)]
    return StatusResponse(
        upload_id=upload_id,
        status=session.status,
        received_count=session.received_count,
        total_chunks=session.total_chunks,
        received_indices=received,
    )


@router.post("/video/{upload_id}/finalize", response_model=FinalizeResponse)
async def finalize_upload(
    upload_id: str,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)
    lock = await _get_upload_lock(upload_id)
    async with lock:
        session = db.get(UploadSession, upload_id)
        if session is None:
            raise HTTPException(status_code=404, detail="アップロードセッションが見つかりません")
        if session.user_id is not None and ctx.user_id is not None and session.user_id != ctx.user_id:
            raise HTTPException(status_code=403, detail="このアップロードへの権限がありません")
        if session.status == "completed":
            return FinalizeResponse(upload_id=upload_id, status="completed",
                                    final_path=session.final_path or "", match_id=session.match_id)
        if session.status != "uploading":
            raise HTTPException(status_code=409, detail=f"セッションは {session.status} 状態です")
        if not _bitmap_complete(session.received_bitmap, session.total_chunks):
            missing = [i for i in range(session.total_chunks) if not _bitmap_get(session.received_bitmap, i)]
            raise HTTPException(status_code=409, detail=f"未受領チャンクがあります ({len(missing)} 件)")

        part = _part_path(upload_id)
        final = _final_path(upload_id, session.filename)
        try:
            part.replace(final)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"ファイルのリネームに失敗: {e}")

        session.status = "completed"
        session.final_path = str(final.resolve())
        session.updated_at = datetime.utcnow()

        # match_id があれば video_local_path を設定
        if session.match_id is not None:
            m = db.get(Match, session.match_id)
            if m is not None:
                # サーバ保管の URL スキームとして server:// を使う（Electron localfile:// と区別）
                m.video_local_path = f"server://{upload_id}{final.suffix}"
                m.video_url = ""

        db.commit()

        return FinalizeResponse(
            upload_id=upload_id,
            status="completed",
            final_path=session.final_path,
            match_id=session.match_id,
        )


@router.delete("/video/{upload_id}")
def abort_upload(
    upload_id: str,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)
    session = db.get(UploadSession, upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="アップロードセッションが見つかりません")
    if session.user_id is not None and ctx.user_id is not None and session.user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="このアップロードへの権限がありません")
    if session.status == "uploading":
        session.status = "aborted"
        session.updated_at = datetime.utcnow()
        db.commit()
    # .part を削除
    try:
        _part_path(upload_id).unlink(missing_ok=True)
    except OSError:
        pass
    return {"success": True}


# ─── Range 対応ストリーミング再生 ─────────────────────────────────────────────

@router.get("/video/by_match/{match_id}/stream")
def stream_video_for_match(
    match_id: int,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """match に紐づくサーバ保管動画を Range 対応でストリーミング。

    レスポンスは部分応答で返すのでブラウザ <video> が seek 可能。
    """
    m = db.get(Match, match_id)
    if m is None:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # アクセス権（既存のロール制約に任せる簡易版）
    from backend.utils.auth import user_can_access_match
    if not user_can_access_match(ctx, m):
        raise HTTPException(status_code=403, detail="この試合へのアクセス権がありません")

    vlp = m.video_local_path or ""
    if not vlp.startswith("server://"):
        raise HTTPException(status_code=404, detail="サーバ保管動画が設定されていません")
    # server://{upload_id}{ext} → ファイル解決
    rest = vlp[len("server://"):]
    file = safe_path(UPLOAD_DIR, rest)
    if not file.exists():
        raise HTTPException(status_code=404, detail="動画ファイルが見つかりません")

    total = file.stat().st_size
    range_header = request.headers.get("range") or request.headers.get("Range")
    start, end = 0, total - 1
    status_code = 200
    if range_header and range_header.startswith("bytes="):
        try:
            part = range_header[6:].split(",")[0]
            s, e = part.split("-")
            if s.strip():
                start = int(s)
            if e.strip():
                end = int(e)
            if start < 0 or end >= total or start > end:
                raise ValueError
            status_code = 206
        except ValueError:
            raise HTTPException(status_code=416, detail="Range ヘッダが不正")

    length = end - start + 1
    chunk_read = 256 * 1024  # 256KB ずつ送出

    def iter_file():
        with open(file, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                buf = f.read(min(chunk_read, remaining))
                if not buf:
                    break
                remaining -= len(buf)
                yield buf

    # 拡張子から Content-Type 推定
    ext = file.suffix.lower()
    ct_map = {
        ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v",
        ".webm": "video/webm", ".mkv": "video/x-matroska",
    }
    content_type = ct_map.get(ext, "application/octet-stream")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": content_type,
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(iter_file(), status_code=status_code, headers=headers, media_type=content_type)


# ─── バックグラウンド GC ─────────────────────────────────────────────────────

async def gc_loop() -> None:
    """アイドルな .part / upload_session を定期クリーンアップ。"""
    from backend.db.database import SessionLocal
    while True:
        try:
            await asyncio.sleep(GC_INTERVAL_SECONDS)
            cutoff = datetime.utcnow() - timedelta(seconds=IDLE_TIMEOUT_SECONDS)
            db = SessionLocal()
            try:
                stale = db.query(UploadSession).filter(
                    UploadSession.status == "uploading",
                    UploadSession.updated_at < cutoff,
                ).all()
                for s in stale:
                    try:
                        _part_path(s.id).unlink(missing_ok=True)
                    except OSError:
                        pass
                    s.status = "expired"
                    s.updated_at = datetime.utcnow()
                if stale:
                    db.commit()
                    print(f"[uploads] GC: expired {len(stale)} idle upload session(s)")
            finally:
                db.close()
            # lock dict の掃除（active でないもの）
            async with _upload_locks_guard:
                for uid in list(_upload_locks.keys()):
                    lk = _upload_locks[uid]
                    if not lk.locked():
                        _upload_locks.pop(uid, None)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[uploads] GC error: {e}")
