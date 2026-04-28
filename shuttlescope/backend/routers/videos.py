"""動画ストリーミング API。

video_token 経由でのみ動画にアクセスできるエンドポイント。
バックエンドはファイルパスを内部で保持し、レスポンスに露出しない。

Range ヘッダー対応により <video> タグからのシーク再生が可能。
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import get_auth, user_can_access_match
from backend.utils.video_token import resolve_token_to_path, is_valid_token_format

logger = logging.getLogger(__name__)
router = APIRouter(tags=["videos"])

_VIDEO_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".m4v": "video/mp4",
    ".ts": "video/mp2t",
    ".mts": "video/mp2t",
}

_CHUNK_SIZE = 1024 * 1024  # 1 MB


def _require_auth(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return ctx


def _resolve_and_authorize(token: str, ctx, db: Session):
    """token を解決し、要求ユーザーが対応 Match にアクセス可能か検証する。

    重要: token を知っているだけではアクセス不可。Match の所有チーム判定
    (user_can_access_match) と組み合わせ、token 漏洩時の被害を最小化する。
    """
    if not is_valid_token_format(token):
        raise HTTPException(status_code=404, detail="動画が見つかりません")
    resolved = resolve_token_to_path(db, token)
    if resolved is None:
        raise HTTPException(status_code=404, detail="動画が見つかりません")
    match, path = resolved
    if not user_can_access_match(ctx, match):
        # 認可失敗も 404 で返す（token の存在を漏らさないため: enumeration 防御）
        # Phase B3: 認可失敗を access_log に記録（漏洩 token の使用試行を検知）
        logger.warning("[videos] access denied: user=%s match=%s",
                       ctx.user_id, match.id)
        try:
            from backend.utils.access_log import log_access
            log_access(
                db, "video_stream_access_denied",
                user_id=ctx.user_id,
                resource_type="match",
                resource_id=match.id,
                details={"actor_role": getattr(ctx, "role", None), "token_prefix": token[:8]},
            )
        except Exception as exc:
            logger.warning("[videos] access_log on deny failed: %s", exc)
        raise HTTPException(status_code=404, detail="動画が見つかりません")
    return match, path


def _parse_range(header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    """Range ヘッダーをパースして (start, end) を返す。形式不正なら None。"""
    if not header or not header.startswith("bytes="):
        return None
    try:
        spec = header[len("bytes="):]
        start_s, _, end_s = spec.partition("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        if start < 0 or end >= file_size or start > end:
            return None
        return start, end
    except (ValueError, TypeError):
        return None


def _file_iter(path: Path, start: int, end: int):
    """指定範囲を chunk 単位で yield する generator。"""
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/videos/{token}/stream")
def stream_video(
    request: Request,
    token: str = PathParam(..., min_length=32, max_length=32),
    db: Session = Depends(get_db),
):
    """video_token に対応する動画を Range サポート付きでストリーミングする。

    認可: ログイン + 試合の所有チーム / 公開プールアクセス権 が必要。
    token を知っていても所有チーム外のユーザーは 404 で拒否される。
    """
    ctx = _require_auth(request)
    _match, path = _resolve_and_authorize(token, ctx, db)

    file_size = path.stat().st_size
    suffix = path.suffix.lower()
    content_type = _VIDEO_MIME.get(suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    range_spec = _parse_range(request.headers.get("range"), file_size)
    if range_spec is None:
        # Range なし: フルファイル送信
        return StreamingResponse(
            _file_iter(path, 0, file_size - 1),
            status_code=200,
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
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


@router.post("/matches/{match_id}/reissue_video_token")
def reissue_video_token(
    request: Request,
    match_id: int = PathParam(..., ge=1, le=2_147_483_647),
    db: Session = Depends(get_db),
):
    """video_token を再発行する（旧トークンは即座に無効化）。

    用途: トークンが漏洩した疑いがある場合に、ボタン一発で新トークンに置換する。
          旧 app://video/{old_token} を持つあらゆる URL は次回アクセスから 404 になる。

    認可: admin / analyst / coach かつ Match の所有チームメンバーのみ。

    冪等性: X-Idempotency-Key ヘッダで二重実行防止。
            同じキーでの 2 回目以降は前回のレスポンスを返す（再発行は実行されない）。
    """
    from backend.db.models import Match
    from backend.utils.video_token import new_token
    from backend.utils.access_log import log_access
    from backend.utils.idempotency import (
        is_valid_key, get_cached, store, replay_response,
    )

    ctx = _require_auth(request)
    if ctx.is_player:
        raise HTTPException(status_code=403, detail="この操作を行う権限がありません")
    match = db.get(Match, match_id)
    if not match or not user_can_access_match(ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 冪等性チェック
    idem_key = request.headers.get("X-Idempotency-Key", "").strip()
    endpoint_id = f"reissue_video_token:{match_id}"
    if idem_key:
        if not is_valid_key(idem_key):
            raise HTTPException(status_code=400, detail="X-Idempotency-Key の形式が不正です")
        cached = get_cached(idem_key, ctx.user_id, endpoint_id)
        if cached is not None:
            logger.info("[videos] idempotent replay: match=%s key=%s",
                        match_id, idem_key[:8])
            return replay_response(cached)

    old_token = match.video_token
    match.video_token = new_token()
    db.commit()
    db.refresh(match)

    try:
        log_access(
            db, "video_token_reissued",
            user_id=ctx.user_id,
            resource_type="match",
            resource_id=match_id,
            details={"actor_role": ctx.role, "had_old_token": bool(old_token),
                     "idempotency_key": idem_key[:8] if idem_key else None},
        )
    except Exception as exc:
        logger.warning("[videos] access_log failed: %s", exc)

    logger.info("[videos] token reissued: match=%s by user=%s", match_id, ctx.user_id)
    response = {
        "success": True,
        "data": {"video_token": match.video_token},
    }
    # 冪等性キーがあれば結果をキャッシュ
    if idem_key:
        store(idem_key, ctx.user_id, endpoint_id, response, status_code=200)
    return response


@router.head("/videos/{token}/stream")
def head_video(
    request: Request,
    token: str = PathParam(..., min_length=32, max_length=32),
    db: Session = Depends(get_db),
):
    """HEAD リクエスト用（ファイルサイズと Content-Type の取得用）。"""
    ctx = _require_auth(request)
    _match, path = _resolve_and_authorize(token, ctx, db)
    file_size = path.stat().st_size
    suffix = path.suffix.lower()
    content_type = _VIDEO_MIME.get(suffix) or "application/octet-stream"
    from starlette.responses import Response
    return Response(
        status_code=200,
        media_type=content_type,
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
        },
    )
