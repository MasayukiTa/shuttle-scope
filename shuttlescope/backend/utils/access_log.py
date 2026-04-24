"""アクセスログ書き込みヘルパー（A-2）+ HMAC ハッシュチェーン（改ざん検知）。

row_hash = HMAC-SHA256(SECRET_KEY, prev_hash || canonical(row))

`canonical(row)` はフィールドの正規化 JSON 文字列。prev_hash は直前の行の row_hash。
途中行の改ざん / 削除 / 挿入は後続 row_hash 不一致として検知できる。
"""
import hashlib
import hmac as _hmac_mod
import json
import logging
import threading
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# INSERT の race による prev_hash 取り違えを防ぐためのプロセス内ロック
_CHAIN_LOCK = threading.Lock()


def _secret_bytes() -> bytes:
    """HMAC 鍵を動的に参照（設定差し替えテストに追従）。

    SECRET_KEY が空の場合でも既知のデフォルト文字列にフォールバックしない。
    既知キーへのフォールバックは監査ログのハッシュチェーンを
    公開鍵で偽造可能にするため、セキュリティ上許容できない。
    """
    from backend.config import settings as _s
    key = (_s.SECRET_KEY or "").encode("utf-8")
    if not key:
        # 空キー時は起動不能にしない（開発時のテスト容易性を保つ）が、
        # 監査チェーンは hostname+pid ベースのランダム派生キーで運用する。
        # これにより「既知デフォルト鍵で署名された audit log を信じる」事態を防ぐ。
        import os, socket
        fallback = f"ss_audit_fallback::{socket.gethostname()}::{os.getpid()}".encode("utf-8")
        return hashlib.sha256(fallback).digest()
    return key


def _canonical(
    user_id: Optional[int],
    action: str,
    resource_type: Optional[str],
    resource_id: Optional[int],
    details: Optional[str],
    ip_addr: Optional[str],
    created_at: datetime,
) -> bytes:
    """並び順固定の正規化 JSON。将来フィールドを追加する場合は末尾に付け足す。"""
    payload = {
        "user_id":       user_id,
        "action":        action,
        "resource_type": resource_type,
        "resource_id":   resource_id,
        "details":       details,
        "ip_addr":       ip_addr,
        "created_at":    created_at.isoformat() if created_at else None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _compute_row_hash(prev_hash: Optional[str], canonical: bytes) -> str:
    mac = _hmac_mod.new(_secret_bytes(), digestmod=hashlib.sha256)
    mac.update((prev_hash or "").encode("ascii"))
    mac.update(b"|")
    mac.update(canonical)
    return mac.hexdigest()


def log_access(
    db,
    action: str,
    user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    details: Optional[dict] = None,
    ip_addr: Optional[str] = None,
) -> None:
    """AccessLog に 1 件書き込む。失敗しても例外を上位に伝播しない。"""
    try:
        from backend.db.models import AccessLog
        details_str = json.dumps(details, ensure_ascii=False) if details else None
        created_at = datetime.utcnow()
        with _CHAIN_LOCK:
            prev = (
                db.query(AccessLog)
                .order_by(AccessLog.id.desc())
                .first()
            )
            prev_hash = prev.row_hash if prev else None
            row_hash = _compute_row_hash(
                prev_hash,
                _canonical(user_id, action, resource_type, resource_id,
                           details_str, ip_addr, created_at),
            )
            entry = AccessLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details_str,
                ip_addr=ip_addr,
                created_at=created_at,
                prev_hash=prev_hash,
                row_hash=row_hash,
            )
            db.add(entry)
            db.commit()
    except Exception as exc:
        logger.warning("access_log write failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def verify_chain(db, limit: Optional[int] = None) -> dict:
    """ハッシュチェーンを先頭から再計算し、食い違う最初の行を返す。

    返り値: {"ok": bool, "checked": int, "total": int, "first_bad_id": Optional[int]}
    """
    from backend.db.models import AccessLog
    q = db.query(AccessLog).order_by(AccessLog.id.asc())
    total = q.count()
    if limit is not None:
        q = q.limit(int(limit))

    prev_hash: Optional[str] = None
    checked = 0
    first_bad: Optional[int] = None
    for row in q.all():
        checked += 1
        # 旧データ（prev_hash / row_hash が null）はスキップして鎖を再開
        if row.row_hash is None:
            prev_hash = None
            continue
        expected = _compute_row_hash(
            row.prev_hash,
            _canonical(row.user_id, row.action, row.resource_type, row.resource_id,
                       row.details, row.ip_addr, row.created_at),
        )
        if row.row_hash != expected or (row.prev_hash or None) != (prev_hash or None):
            first_bad = row.id
            break
        prev_hash = row.row_hash

    return {
        "ok": first_bad is None,
        "checked": checked,
        "total": total,
        "first_bad_id": first_bad,
    }
