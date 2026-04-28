"""緊急セキュリティ操作 API (Phase C2)。

漏洩発生時に admin が即座に封じ込めるためのエンドポイント。

エンドポイント:
  POST /api/admin/security/revoke_all_tokens         全 JWT を即座に失効 (DB ベース)
  POST /api/admin/security/reissue_all_video_tokens  全 Match の video_token を一斉再発行
  GET  /api/admin/security/audit_log                 access_log の閲覧 (フィルタ付き)

認可: admin ロールのみ。
監査: 各操作は access_log に "emergency_*" として記録される。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin_security"])


def _require_admin(request: Request):
    ctx = get_auth(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin ロールが必要です")
    return ctx


@router.post("/admin/security/revoke_all_tokens")
def revoke_all_tokens(request: Request, db: Session = Depends(get_db)):
    """全ユーザーの JWT を一斉失効する (DB ブラックリスト方式)。

    動作:
      - revoked_tokens テーブルに `mass_revoke` マーカーを追加
      - 同マーカー以前に発行された全トークンは検証時に拒否される
      - 全ユーザーが再ログインを要求される

    用途: SECRET_KEY 漏洩疑惑 / 大規模インシデント発生時の封じ込め
    """
    ctx = _require_admin(request)

    revoked_count = 0
    try:
        # 既存 revoked_tokens テーブルを利用 (個別 jti レコードを大量追加するのは非現実的なため、
        # 別途 mass_revoke_at タイムスタンプを system_settings に持つ方式を採用)
        from backend.db.models import RevokedToken
        from backend.utils.access_log import log_access

        # システム全体の mass_revoke_at を更新（JWT 検証時にこのタイムスタンプより
        # 古い iat を持つトークンは全て失効扱い）
        sentinel_jti = f"__mass_revoke_{datetime.utcnow().isoformat()}"
        try:
            r = RevokedToken(jti=sentinel_jti, expires_at=datetime.utcnow() + timedelta(days=365))
            db.add(r)
            db.commit()
            revoked_count = 1
        except Exception as exc:
            db.rollback()
            logger.warning("[admin_security] revoke sentinel insert failed: %s", exc)

        log_access(
            db, "emergency_revoke_all_tokens",
            user_id=ctx.user_id,
            details={"actor_role": ctx.role, "sentinel": sentinel_jti},
        )
        # キャッシュを即座に無効化して、次の verify_token から sentinel を見るようにする
        try:
            from backend.utils.jwt_utils import _MASS_REVOKE_CACHE
            _MASS_REVOKE_CACHE["ts"] = 0.0
            _MASS_REVOKE_CACHE["value"] = None
        except Exception:
            pass
    except Exception as exc:
        logger.error("[admin_security] revoke_all_tokens failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"失効処理に失敗: {exc}")

    logger.warning("[admin_security] EMERGENCY: all tokens revoked by user=%s", ctx.user_id)
    return {
        "success": True,
        "data": {
            "revoked_marker_added": bool(revoked_count),
            "next_step": "全ユーザーが再ログインを要求されます。SECRET_KEY のローテーションも検討してください。",
        },
    }


@router.post("/admin/security/reissue_all_video_tokens")
def reissue_all_video_tokens(
    request: Request,
    db: Session = Depends(get_db),
):
    """全 Match の video_token を一斉再発行する。

    用途: video_token の大量漏洩、または鍵漏洩疑惑時の即時封じ込め。
    動作: 全 Match の video_token を新 UUID4 に置換 (旧 token は次回アクセスで 404)。
    """
    ctx = _require_admin(request)

    from backend.db.models import Match
    from backend.utils.video_token import new_token
    from backend.utils.access_log import log_access

    matches = db.query(Match).filter(Match.video_local_path.isnot(None)).all()
    updated = 0
    for m in matches:
        m.video_token = new_token()
        updated += 1
    db.commit()

    log_access(
        db, "emergency_reissue_all_video_tokens",
        user_id=ctx.user_id,
        details={"actor_role": ctx.role, "match_count": updated},
    )

    logger.warning("[admin_security] EMERGENCY: %d video_tokens reissued by user=%s",
                   updated, ctx.user_id)
    return {
        "success": True,
        "data": {
            "reissued_count": updated,
            "next_step": "全ユーザーは試合一覧を再読み込みすると新しい video_token で再生可能になります。",
        },
    }


@router.get("/admin/security/audit_log")
def get_audit_log(
    request: Request,
    db: Session = Depends(get_db),
    event: Optional[str] = Query(None, max_length=100),
    user_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    since_hours: int = Query(24, ge=1, le=24 * 30),
    limit: int = Query(500, ge=1, le=5000),
):
    """access_log を admin から参照する。

    クエリパラメータ:
      event: イベント名で絞り込み (前方一致)
      user_id: 実行者 user_id で絞り込み
      since_hours: 過去何時間分を返すか (デフォルト 24h、最大 720h=30 日)
      limit: 取得最大件数 (デフォルト 500)
    """
    ctx = _require_admin(request)

    try:
        from backend.db.models import AccessLog
    except ImportError:
        raise HTTPException(status_code=501, detail="AccessLog モデルが存在しません")

    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    q = db.query(AccessLog).filter(AccessLog.created_at >= cutoff)
    if event:
        # AccessLog の列名は "action" (login/logout/export/deny 等)。"event" 互換のため
        # フィルタ引数名は維持しつつ、参照は action に揃える。
        q = q.filter(AccessLog.action.startswith(event))
    if user_id:
        q = q.filter(AccessLog.user_id == user_id)
    rows = q.order_by(AccessLog.created_at.desc()).limit(limit).all()

    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                # API 互換のため UI 側に "event" として返す（実体は action 列）
                "event": r.action,
                "user_id": r.user_id,
                "resource_type": getattr(r, "resource_type", None),
                "resource_id": getattr(r, "resource_id", None),
                "ip_addr": getattr(r, "ip_addr", None),
                "details": getattr(r, "details", None),
                "created_at": r.created_at,  # UTCJSONResponse + ENCODERS_BY_TYPE が ISO+"Z" 化
            }
            for r in rows
        ],
        "meta": {"count": len(rows), "since_hours": since_hours, "limit": limit},
    }
