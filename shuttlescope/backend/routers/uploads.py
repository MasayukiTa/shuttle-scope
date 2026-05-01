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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, UploadSession
from backend.utils.auth import AuthCtx, get_auth
from backend.utils.safe_path import safe_path


router = APIRouter(prefix="/v1/uploads", tags=["uploads"])

# ─── 定数 ─────────────────────────────────────────────────────────────────────

UPLOAD_DIR = Path(os.path.abspath("./videos"))
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024 * 1024         # 50GB/ファイル (高性能カメラの長時間録画想定)
MAX_RECORDING_DURATION_MIN = int((__import__("os").environ.get("SS_SENDER_MAX_RECORDING_DURATION_MIN") or 180))
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
    # extra フィールドの silent drop を遮断 (mass-assignment 防御)。
    model_config = {"extra": "forbid"}
    match_id: Optional[int] = None
    # filename は表示・DB 保存用。実ファイル名は upload_id ベースに正規化されるため
    # path traversal の直接被害は無いが、CRLF / 制御文字を入れて DB に保存して
    # 後続の表示やログを汚染する経路を塞ぐ。長さは 255 byte (DB column 上限) 想定。
    filename: str = Field(..., min_length=1, max_length=255)
    total_size: int
    chunk_size: int = DEFAULT_CHUNK_SIZE
    mime_type: Optional[str] = Field(default=None, max_length=128)
    # R-1: MediaRecorder のように事前にファイルサイズが分からない経路では True。
    # chunk は append モードで受領し、finalize 時にサイズを確定する。
    # streaming=True の場合、total_size は上限 (5GB 等) として扱われる。
    streaming: bool = False


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

    # filename に NUL / CR / LF / その他制御文字が混入すると、後続の表示・
    # ログ出力・Content-Disposition ヘッダ生成等で破壊的に振る舞う可能性がある。
    # path traversal そのものは upload_id ベースの保存と suffix 白リストで防げているが、
    # 文字種は事前に絞っておく (defense in depth, CWE-93 / CWE-138)。
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in body.filename):
        raise HTTPException(status_code=422, detail="filename に制御文字を含めることはできません")
    # B-2 強化: HTML タグ / Path Traversal / 危険な文字 を拒否 (Stored XSS + path traversal)
    _BAD_FNAME_CHARS = ("<", ">", "\"", "'", "&", "\\", "/", "..", "\x00")
    if any(c in body.filename for c in _BAD_FNAME_CHARS):
        raise HTTPException(status_code=422, detail="filename に許可されない文字が含まれています")
    # 拡張子ホワイトリスト (B-3, B-6)
    _ALLOWED_VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v", ".ts", ".mts"}
    from pathlib import Path as _P
    if _P(body.filename).suffix.lower() not in _ALLOWED_VIDEO_EXTS:
        raise HTTPException(status_code=422, detail=f"動画ファイル拡張子のみ許可: {_ALLOWED_VIDEO_EXTS}")

    # streaming モードでは total_size は上限値として扱う (確定サイズではない)。
    if body.streaming:
        if body.total_size <= 0 or body.total_size > MAX_UPLOAD_SIZE:
            raise HTTPException(status_code=400, detail=f"streaming 経路でも total_size 上限は 1〜{MAX_UPLOAD_SIZE} byte")
    elif body.total_size <= 0 or body.total_size > MAX_UPLOAD_SIZE:
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
    try:
        if body.streaming:
            # streaming は append モード。空ファイルだけ作る。
            with open(part, "wb") as f:
                pass
        else:
            # sparse file 確保。truncate で total_size を確定。
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
        streaming=body.streaming,
    )
    db.add(session)
    db.commit()

    return InitResponse(
        upload_id=upload_id,
        chunk_size=body.chunk_size,
        total_chunks=total_chunks,
        received_indices=[],
    )


_VIDEO_MAGIC_BYTES = {
    # mp4 / m4v / mov: ftyp box at offset 4
    b"ftyp": (4, "mp4/mov"),
    # webm / mkv: EBML header
    b"\x1a\x45\xdf\xa3": (0, "webm/mkv"),
    # mpegts: 0x47 sync byte at offset 0 (188 byte cycle)
    b"\x47": (0, "mpegts"),
    # avi: RIFF
    b"RIFF": (0, "avi/wav"),
}


def _validate_video_container(path) -> tuple[bool, str]:
    """C-5/C-6 防御 (round112): ファイル全体のコンテナ構造を validate する。

    優先順:
      1) ffprobe があれば --show_streams で codec_type=video を確認 (最も堅牢)
      2) Python で MP4 atom (ftyp + moov + mdat) / EBML (Segment) / RIFF (AVI) を確認

    Returns (ok, reason)
    """
    import shutil as _sh, subprocess as _sp
    p = path
    try:
        size = p.stat().st_size
    except OSError as e:
        return False, f"stat: {e}"
    if size < 32:
        return False, "ファイルが小さすぎます"

    # 1) ffprobe 経由
    ffprobe = _sh.which("ffprobe")
    if ffprobe:
        try:
            proc = _sp.run(
                [ffprobe, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", "--", str(p)],
                capture_output=True, timeout=30, shell=False,
            )
            if proc.returncode != 0:
                return False, "ffprobe rc!=0"
            import json as _json
            info = _json.loads(proc.stdout or b"{}")
            if any(s.get("codec_type") == "video" for s in info.get("streams", [])):
                return True, "ffprobe ok"
            return False, "no video stream"
        except Exception as e:
            # fall through to Python parser
            pass

    # 2) Python parser fallback
    try:
        with open(p, "rb") as f:
            head = f.read(16)
            # MP4 / MOV: top-level atoms (ftyp が先頭、moov/mdat のいずれか必須)
            if head[4:8] == b"ftyp":
                return _validate_mp4_atoms(p, size)
            # EBML (Matroska / WebM)
            if head[:4] == b"\x1a\x45\xdf\xa3":
                # EBML ヘッダ後に Segment ID (0x18538067) を確認
                f.seek(0)
                blob = f.read(min(size, 4096))
                if b"\x18\x53\x80\x67" in blob:
                    return True, "ebml ok"
                return False, "no ebml segment"
            # AVI (RIFF + AVI signature)
            if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
                return True, "avi ok"
            # mpegts (sync byte every 188 bytes)
            if head[:1] == b"\x47":
                f.seek(188)
                if f.read(1) == b"\x47":
                    return True, "mpegts ok"
                return False, "mpegts sync mismatch"
            return False, "unknown container"
    except Exception as e:
        return False, f"parse error: {type(e).__name__}"


def _validate_mp4_atoms(path, file_size: int) -> tuple[bool, str]:
    """MP4 / MOV: ftyp 直後の top-level atom を順に walk して moov / mdat の存在を確認。

    各 atom は [size:4][type:4][...]; size==1 なら直後 8 byte が 64bit size。
    size==0 は EOF までを意味する (mdat の末尾)。
    任意のオフセットで size が 0/8 未満 / file_size 超過なら corrupt と判定。
    """
    seen_types: set[bytes] = set()
    try:
        with open(path, "rb") as f:
            offset = 0
            steps = 0
            while offset + 8 <= file_size and steps < 200:
                f.seek(offset)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                box_size = int.from_bytes(hdr[:4], "big")
                box_type = hdr[4:8]
                if box_size == 1:
                    # 64bit largesize
                    big = f.read(8)
                    if len(big) < 8:
                        return False, "truncated 64bit size"
                    box_size = int.from_bytes(big, "big")
                elif box_size == 0:
                    # EOF まで
                    box_size = file_size - offset
                if box_size < 8 or offset + box_size > file_size:
                    return False, f"corrupt atom {box_type!r} at {offset}"
                seen_types.add(box_type)
                offset += box_size
                steps += 1
            if b"ftyp" not in seen_types:
                return False, "no ftyp"
            if b"moov" not in seen_types:
                return False, "no moov atom (動画メタデータが欠落)"
            if b"mdat" not in seen_types:
                return False, "no mdat atom (メディアデータが欠落)"
            return True, "mp4 atoms ok"
    except Exception as e:
        return False, f"mp4 walk error: {type(e).__name__}"


def _looks_like_video(first_bytes: bytes) -> bool:
    """先頭バイトから動画らしさを判定 (B-3 magic bytes 検証)。"""
    if len(first_bytes) < 16:
        return False
    if first_bytes[4:8] == b"ftyp":
        return True
    if first_bytes[:4] == b"\x1a\x45\xdf\xa3":  # webm/mkv
        return True
    if first_bytes[:4] == b"RIFF":
        return True
    if first_bytes[0:1] == b"\x47" and len(first_bytes) >= 188 and first_bytes[188:189] in (b"\x47", b""):
        return True
    return False


@router.post("/video/chunk")
async def upload_chunk(
    request: Request,
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    chunk: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    _require_writer(ctx)

    # B-8: Content-Encoding 制限 (gzip/br/deflate decompress bomb 防御)
    enc = (request.headers.get("content-encoding") or "").strip().lower()
    if enc and enc not in ("identity", ""):
        raise HTTPException(status_code=415, detail=f"Content-Encoding={enc} は許可されません")

    sem = _get_global_sem()
    async with sem:
        lock = await _get_upload_lock(upload_id)
        async with lock:
            session = db.get(UploadSession, upload_id)
            if session is None:
                raise HTTPException(status_code=404, detail="アップロードセッションが見つかりません")
            if session.status != "uploading":
                raise HTTPException(status_code=409, detail=f"セッションは {session.status} 状態です")
            # 所有者チェック (D-2 強化、毎 chunk で必ず確認)
            if session.user_id is not None and ctx.user_id is not None and session.user_id != ctx.user_id:
                raise HTTPException(status_code=403, detail="このアップロードへの権限がありません")
            if chunk_index < 0:
                raise HTTPException(status_code=400, detail="chunk_index が範囲外です")
            is_streaming = bool(getattr(session, "streaming", False))
            if not is_streaming and chunk_index >= session.total_chunks:
                raise HTTPException(status_code=400, detail="chunk_index が範囲外です")
            if is_streaming and chunk_index >= 65535:
                # streaming でも上限を設けて DoS 抑制
                raise HTTPException(status_code=400, detail="streaming chunk_index 上限超過")

            # B-3 強化: magic bytes バイパス防御。
            # chunk_index=0 が先に届く前に他 chunk を受け付けると、攻撃者が後から
            # 偽の mp4 ヘッダだけ送って type 検証をすり抜けられる。先頭が来るまで他は拒否。
            if chunk_index != 0 and not _bitmap_get(session.received_bitmap, 0):
                raise HTTPException(
                    status_code=409,
                    detail="先頭 chunk (index=0) を最初に送信してください (magic bytes 検証のため)",
                )

            # 既に受領済みならスキップ（冪等）
            if _bitmap_get(session.received_bitmap, chunk_index):
                return {"success": True, "already_received": True, "received_count": session.received_count}

            # チャンクを読む。
            data = await chunk.read()
            if not data:
                raise HTTPException(status_code=400, detail="空チャンクは拒否")

            # B-3 magic bytes 検証 (chunk_index=0 のとき先頭バイトを動画判定)
            if chunk_index == 0:
                if not _looks_like_video(data[:256]):
                    raise HTTPException(
                        status_code=415,
                        detail="先頭バイトが動画フォーマットと一致しません (mp4/webm/mkv/mov/avi/ts のみ許可)",
                    )
            if is_streaming:
                # streaming: chunk は append。順序は chunk_index 順を強制。
                if chunk_index != session.received_count:
                    raise HTTPException(
                        status_code=409,
                        detail=f"streaming は順次送信必須 (expected={session.received_count}, got={chunk_index})",
                    )
                if len(data) > session.chunk_size:
                    raise HTTPException(status_code=400, detail=f"chunk_size 上限超過 ({len(data)} > {session.chunk_size})")
                # 累積上限チェック (DoS 防御)
                running_total = (session.total_size or 0)
                # streaming では total_size は上限 (init 時)。ここでは別途 final size を追跡しない。
                # ファイルサイズ自体で確認する。
                part = _part_path(upload_id)
                try:
                    cur_size = part.stat().st_size if part.exists() else 0
                except OSError:
                    cur_size = 0
                if cur_size + len(data) > MAX_UPLOAD_SIZE:
                    raise HTTPException(status_code=413, detail="streaming 累積サイズが MAX_UPLOAD_SIZE を超過")

                def _append() -> None:
                    with open(part, "ab") as f:
                        f.write(data)

                await asyncio.get_event_loop().run_in_executor(None, _append)
            else:
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

            bitmap_size = max(session.total_chunks, chunk_index + 1)
            session.received_bitmap = _bitmap_set(session.received_bitmap, chunk_index, bitmap_size)
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
        is_streaming = bool(getattr(session, "streaming", False))
        if is_streaming:
            # streaming は順次 append 済み。最低 1 chunk 必要。
            if session.received_count <= 0:
                raise HTTPException(status_code=409, detail="streaming に chunk が 1 つも届いていません")
        elif not _bitmap_complete(session.received_bitmap, session.total_chunks):
            missing = [i for i in range(session.total_chunks) if not _bitmap_get(session.received_bitmap, i)]
            raise HTTPException(status_code=409, detail=f"未受領チャンクがあります ({len(missing)} 件)")
        # E-3: 録画開始からの経過時間が上限を超えたら拒否 (DoS 防止)
        if session.created_at:
            elapsed_min = (datetime.utcnow() - session.created_at).total_seconds() / 60
            if elapsed_min > MAX_RECORDING_DURATION_MIN:
                raise HTTPException(
                    status_code=413,
                    detail=f"録画時間が上限 ({MAX_RECORDING_DURATION_MIN} 分) を超えています",
                )

        part = _part_path(upload_id)
        final = _final_path(upload_id, session.filename)
        try:
            part.replace(final)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"ファイルのリネームに失敗: {e}")

        # C-5/C-6 防御 (round112): 先頭 256 byte の magic bytes だけでは ftypisom +
        # 任意の HTML / shell script を通してしまう。finalize 時にコンテナ構造を再 validate する。
        # 1) ffprobe があればそれを使う (堅牢)
        # 2) なければ Python で MP4 atom / EBML / RIFF をパースして moov/mdat 等の存在を確認
        try:
            valid, reason = _validate_video_container(final)
            if not valid:
                try: final.unlink(missing_ok=True)
                except Exception: pass
                session.status = "aborted"
                db.commit()
                raise HTTPException(
                    status_code=422,
                    detail=f"動画として無効です (コンテナ検証失敗: {reason})",
                )
        except HTTPException:
            raise
        except Exception as _ffex:
            import logging as _lg
            _lg.getLogger(__name__).warning("[uploads] container validate skipped: %s", _ffex)

        session.status = "completed"
        session.final_path = str(final.resolve())
        session.updated_at = datetime.utcnow()
        # streaming は実ファイルサイズで total_size を確定
        if is_streaming:
            try:
                session.total_size = final.stat().st_size
            except OSError:
                pass

        # match_id があれば video_local_path を設定
        if session.match_id is not None:
            m = db.get(Match, session.match_id)
            if m is not None:
                # サーバ保管の URL スキームとして server:// を使う（Electron localfile:// と区別）
                m.video_local_path = f"server://{upload_id}{final.suffix}"
                m.video_url = ""
                # video_token がなければ発行 (Phase 1 の app://video/{token} 経路用)
                from backend.utils.video_token import new_token as _new_video_token
                if not getattr(m, "video_token", None):
                    m.video_token = _new_video_token()

        # R-1: ServerVideoArtifact を生成 (Sender からの自動録画ストリームの記録)
        try:
            from backend.db.models import ServerVideoArtifact as _SVA
            file_size = final.stat().st_size if final.exists() else None
            artifact = _SVA(
                match_id=session.match_id,
                upload_id=upload_id,
                sender_user_id=ctx.user_id,
                file_path=str(final.resolve()),
                file_size_bytes=file_size,
                mime_type=session.mime_type,
                started_at=session.created_at,
                finalized_at=datetime.utcnow(),
            )
            db.add(artifact)
        except Exception as exc:
            import logging as _lg
            _lg.getLogger(__name__).warning("[uploads] artifact create failed: %s", exc)

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
    # アクセス権チェック: 動画は機微なメディアなので team scope (require_match_scope)
    # まで厳格化する。これまでの `user_can_access_match` は coach/analyst を素通りさせ、
    # cross-team で他チームの動画ストリームを抜ける scope leak が成立していた。
    # comments/sessions/reports と同じ scope ヘルパに統一する。
    from backend.utils.auth import require_match_scope as _require_match_scope
    _require_match_scope(request, m, db)

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
