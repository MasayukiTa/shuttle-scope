"""Export パッケージの HMAC-SHA256 署名 + 有効期限 + 1 回利用制限。

Phase A3 セキュリティ強化:
  - sign_package(): 署名・nonce・有効期限を埋め込む
  - verify_package(): 署名検証 + 期限チェック + nonce 重複チェック (DB 経由)
  - 鍵は SS_EXPORT_SIGNING_KEY 環境変数 (32 bytes hex)
  - 鍵ローテで全 export パッケージを即無効化可能
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Export パッケージのデフォルト有効期限（24 時間）
DEFAULT_TTL_HOURS = 24

# 署名フィールド名（payload 内に埋め込む特殊キー）
SIG_FIELD = "_signature"
NONCE_FIELD = "_nonce"
EXPIRES_FIELD = "_expires_at"
ISSUED_FIELD = "_issued_at"


def _signing_key() -> Optional[bytes]:
    """SS_EXPORT_SIGNING_KEY を取得する。"""
    try:
        from backend.config import settings
        v = (getattr(settings, "ss_export_signing_key", "") or "").strip()
    except Exception:
        v = (os.environ.get("SS_EXPORT_SIGNING_KEY", "") or "").strip()
    return v.encode("utf-8") if v else None


def _canonical_json(payload: dict) -> bytes:
    """署名対象を決定論的な JSON にシリアライズする (キーソート + ASCII)。

    これにより同じ内容ならどの環境でも同じ署名が得られる。
    """
    # 署名フィールド自体は除外して計算する
    body = {k: v for k, v in payload.items() if k != SIG_FIELD}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign_package(payload: dict, ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    """payload に nonce / expires_at / signature を埋め込んで返す。

    鍵未設定時は警告ログを出して未署名の payload を返す（後方互換）。
    """
    key = _signing_key()
    if key is None:
        logger.warning(
            "[export_signing] SS_EXPORT_SIGNING_KEY 未設定。Export パッケージは未署名で作成されます。"
        )
        return payload

    now = datetime.utcnow()
    payload[NONCE_FIELD] = uuid.uuid4().hex
    payload[ISSUED_FIELD] = now.isoformat()
    payload[EXPIRES_FIELD] = (now + timedelta(hours=ttl_hours)).isoformat()
    sig = hmac.new(key, _canonical_json(payload), hashlib.sha256).hexdigest()
    payload[SIG_FIELD] = sig
    return payload


def verify_package(payload: dict, db: Optional[Session] = None) -> Tuple[bool, str]:
    """Export パッケージの署名・期限・nonce を検証する。

    Returns: (ok, reason)
      ok=True なら検証成功。False の場合 reason に失敗理由が入る。
    """
    key = _signing_key()
    if key is None:
        # 鍵未設定 → 検証スキップ（後方互換だが本番では危険）
        logger.warning("[export_signing] 鍵未設定のため Import 時の署名検証をスキップ")
        return True, "signing_key_not_configured"

    sig = payload.get(SIG_FIELD)
    if not sig:
        return False, "署名がありません (_signature 欠落)"

    nonce = payload.get(NONCE_FIELD)
    if not nonce or not isinstance(nonce, str) or len(nonce) != 32:
        return False, "nonce が不正です"

    expires_at_str = payload.get(EXPIRES_FIELD)
    if not expires_at_str:
        return False, "有効期限が設定されていません"
    # D-3 防御 (round113): Python 3.11+ は 'Z' suffix を受理し tz-aware を返すため
    # naive utcnow との比較で TypeError を起こす。tz を一括 strip して扱う。
    try:
        s = expires_at_str
        if s.endswith("Z"): s = s[:-1] + "+00:00"
        expires_at = datetime.fromisoformat(s)
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None) - (expires_at.utcoffset() or timedelta(0))
    except (ValueError, TypeError):
        return False, "有効期限の形式が不正です"
    try:
        if datetime.utcnow() > expires_at:
            return False, f"パッケージの有効期限切れ (期限: {expires_at_str})"
    except TypeError:
        return False, "有効期限の形式が不正です (タイムゾーン不整合)"

    expected = hmac.new(key, _canonical_json(payload), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False, "署名検証失敗 (改ざんまたは鍵不一致)"

    # nonce 重複チェック (DB 経由)
    if db is not None:
        try:
            from backend.db.models import ConsumedExportNonce  # type: ignore
            existing = db.query(ConsumedExportNonce).filter(
                ConsumedExportNonce.nonce == nonce
            ).one_or_none()
            if existing is not None:
                return False, f"nonce は使用済みです (二重インポート防止)"
        except Exception as exc:
            # テーブル未作成時は警告のみ
            logger.warning("[export_signing] nonce 重複チェック失敗: %s", exc)

    return True, "ok"


def consume_nonce(db: Session, nonce: str) -> None:
    """検証成功後、nonce を消費済みとして DB に記録する。"""
    try:
        from backend.db.models import ConsumedExportNonce  # type: ignore
        record = ConsumedExportNonce(nonce=nonce, consumed_at=datetime.utcnow())
        db.add(record)
        db.commit()
    except Exception as exc:
        logger.error("[export_signing] nonce 記録失敗: %s", exc)
        db.rollback()
