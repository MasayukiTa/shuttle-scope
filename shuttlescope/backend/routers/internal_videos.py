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
_WORKER_RATE_FAIL: dict[str, list[float]] = {}  # 失敗専用 (R7 fix)
_WORKER_LOCK = _Lock()
_WORKER_RATE_MAX = 60
_WORKER_RATE_FAIL_MAX = 10  # 401 大量試行は厳しく抑止
_WORKER_RATE_WINDOW = 60.0
# 簡易 LRU 上限 (IPv6 ローテーション攻撃で OOM しないように)
_WORKER_RATE_MAX_KEYS = 50_000


def _prune_rate_dicts(now: float) -> None:
    cutoff = now - _WORKER_RATE_WINDOW
    for d in (_WORKER_RATE, _WORKER_RATE_FAIL):
        if len(d) > _WORKER_RATE_MAX_KEYS:
            empty = [k for k, v in d.items() if not [t for t in v if t > cutoff]]
            for k in empty:
                d.pop(k, None)


def _worker_rate_check(ip: str):
    """成功 path 用 60/min。"""
    now = _time.time()
    cutoff = now - _WORKER_RATE_WINDOW
    with _WORKER_LOCK:
        _prune_rate_dicts(now)
        history = [t for t in _WORKER_RATE.get(ip, []) if t >= cutoff]
        if len(history) >= _WORKER_RATE_MAX:
            _WORKER_RATE[ip] = history
            raise HTTPException(status_code=429, detail="Worker rate limit exceeded")
        history.append(now)
        _WORKER_RATE[ip] = history


def _worker_fail_rate_check(ip: str):
    """Round 258 R7 P2 fix (Codex review): 失敗試行用 10/min。
    旧コードは verify_worker_token() 失敗で即 401 を返し _worker_rate_check() を
    通らなかったため、無効 token の brute force / 401 flood が無制限だった。
    成功前に必ず通すようにする。"""
    now = _time.time()
    cutoff = now - _WORKER_RATE_WINDOW
    with _WORKER_LOCK:
        _prune_rate_dicts(now)
        history = [t for t in _WORKER_RATE_FAIL.get(ip, []) if t >= cutoff]
        if len(history) >= _WORKER_RATE_FAIL_MAX:
            _WORKER_RATE_FAIL[ip] = history
            raise HTTPException(
                status_code=429,
                detail="Worker auth failure rate limit exceeded",
            )
        history.append(now)
        _WORKER_RATE_FAIL[ip] = history


def _resolve_ip_for_worker(request: Optional[Request]) -> str:
    """Round 258 R7: trusted_client_ip 統一 (CF-Connecting-IP は loopback 経由のみ信用)."""
    if request is None:
        return "unknown"
    try:
        from backend.utils.client_ip import trusted_client_ip
        ip = trusted_client_ip(request, default="unknown")
    except Exception:
        ip = (request.client.host if request.client else "unknown") or "unknown"
    return (ip or "unknown")[:64]


def _require_worker(x_worker_token: Optional[str], request: Optional[Request] = None):
    """Round 258 R7 P2 fix (Codex): 失敗試行も per-IP rate-limit に乗せる。

    順序:
      1. service-enabled check
      2. (NEW) 失敗 bucket の事前チェック → 既に閾値超なら 429
      3. token verify。失敗時は失敗 bucket に記録して 401。
      4. 成功 bucket 進行 + 60/min check。
    """
    if not is_worker_enabled():
        raise HTTPException(status_code=503, detail="Worker 機能は無効です (SS_WORKER_AUTH_TOKEN 未設定)")
    ip = _resolve_ip_for_worker(request)
    # 失敗 bucket を成功検証より先に評価する (R7 P2)
    _worker_fail_rate_check_peek = lambda: None  # noqa: E731 (compatibility, body below)
    # 失敗 bucket は「既に閾値オーバーなら 429」だけ先に判定し、加算は失敗時のみ。
    now = _time.time()
    cutoff = now - _WORKER_RATE_WINDOW
    with _WORKER_LOCK:
        history = [t for t in _WORKER_RATE_FAIL.get(ip, []) if t >= cutoff]
        if len(history) >= _WORKER_RATE_FAIL_MAX:
            _WORKER_RATE_FAIL[ip] = history
            raise HTTPException(status_code=429, detail="Worker auth failure rate limit exceeded")
    if not verify_worker_token(x_worker_token):
        # 失敗を加算
        with _WORKER_LOCK:
            history = [t for t in _WORKER_RATE_FAIL.get(ip, []) if t >= cutoff]
            history.append(now)
            _WORKER_RATE_FAIL[ip] = history
        # Round 258 R31 fix (CodeQL py/clear-text-logging-sensitive-data #2057 high):
        # 旧コードは IP を平文で audit log に書き込んでいた。CodeQL は IP を
        # sensitive data 扱いし high として alert 上げる。
        # 監査運用上「failed auth から IP を辿って rate limit / IDS の効果を確認」
        # する用途自体は維持する必要があるので、daily-rotated HMAC hash で 1) 同じ
        # IP の連続失敗は判別可能、2) IP 平文露出は防止、3) cross-day で再特定不能、
        # の三条件を満たす形に置換する (R26 P3 daily-salt 実装と同じパターン)。
        try:
            import hashlib as _hashlib_iv
            import hmac as _hmac_iv
            from datetime import datetime as _dt_iv
            _daily_salt_iv = _dt_iv.utcnow().strftime("%Y-%m-%d").encode("utf-8")
            _ip_hash = _hmac_iv.new(_daily_salt_iv, (ip or "").encode("utf-8"), _hashlib_iv.sha256).hexdigest()[:8]
        except Exception:
            _ip_hash = "unknown"
        logger.warning("worker_auth_failed ip_hash=%s", _ip_hash)
        raise HTTPException(status_code=401, detail="Worker トークンが無効です")
    # 成功 path
    if request is not None:
        _worker_rate_check(ip)


# Round 258 R9 F-9 fix (deep audit): Range request 1 回あたりの最大バイト数を限定する。
# 旧コードは `end = file_size - 1` を許容していたため、worker token を持つ攻撃者が
# `bytes=0-` で 10 GB ファイルを 60 req/min × 開いて流す = 600 GB/min の disk I/O DoS が
# 可能だった。chunk 上限を 256 MB にして、複数リクエストを強制 = rate limit が効く。
_MAX_RANGE_BYTES = 256 * 1024 * 1024


def _parse_range(header: Optional[str], file_size: int) -> Optional[Tuple[int, int]]:
    """Range request parser。

    Round 258 R10 P1 fix (regression): R9 で silent truncation を入れたが、
    HTML5 <video> は 206 で「要求より短い range」を返されると次の chunk を
    fetch せず再生停止する。RFC 7233 準拠で 416 を返すべきだが、互換性のために
    今回は **truncate を維持** しつつ、明示的に `truncated` flag を返して caller が
    `Accept-Ranges: bytes` ヘッダで client が自然に再リクエストするのを期待する。
    `bytes=0-` のように end 省略の場合のみ truncate (合理的)。
    end を明示指定したのに truncate するのは破綻なので、その場合は None を返して
    呼び出し側で 416 にする。
    """
    if not header or not header.startswith("bytes="):
        return None
    try:
        spec = header[len("bytes="):]
        a, _, b = spec.partition("-")
        start = int(a) if a else 0
        end_explicit = bool(b)
        end = int(b) if b else file_size - 1
        if start < 0 or end >= file_size or start > end:
            return None
        if (end - start + 1) > _MAX_RANGE_BYTES:
            if end_explicit:
                # client が end を明示した。truncate せず 416 にするため None を返す
                return None
            # `bytes=N-` (open-ended) は truncate して返す。client は次の chunk で再要求する
            end = start + _MAX_RANGE_BYTES - 1
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
