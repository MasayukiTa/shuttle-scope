"""Growth Advisor チャット router。

coach / analyst / admin のみ利用可能。player は 403。

エンドポイント:
  POST   /api/insights/chat/sessions                 -- セッション作成
  GET    /api/insights/chat/sessions/{sid}/messages  -- 履歴取得
  POST   /api/insights/chat/sessions/{sid}/messages  -- メッセージ送信
  DELETE /api/insights/chat/sessions/{sid}           -- soft-delete + 匿名化

セーフティ:
  - rate-limit: 1 メッセージ / 2 秒 / ユーザ (in-memory)
  - sanitize_user_input(): injection_attempt 検知 → 安全な定型応答
  - check_and_record_budget(): 日次トークン予算超過 → 429
  - HarnessedGenerator + TemplateGenerator フォールバックで安全に応答
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import ChatMessage, ChatSession
from backend.utils.auth import AuthCtx, get_auth
from backend.analysis.insights import get_generator
from backend.analysis.insights.types import InsightContext
from backend.analysis.insights.safety import (
    check_and_record_budget,
    sanitize_user_input,
)


router = APIRouter()


_ALLOWED_ROLES = {"coach", "analyst", "admin"}
# in-memory rate-limit: {user_id: last_message_ts_seconds}
_RATE_LIMIT: dict[int, float] = {}
_RATE_LIMIT_SECONDS = 2.0
# 1 メッセージあたりの概算トークン数 (input+output 合算の粗い見積)
_APPROX_TOKENS_PER_MESSAGE = 200

# Injection 検知時に返す安全な定型応答
_SAFE_REFUSAL_JA = (
    "申し訳ありませんが、その内容にはお応えできません。"
    "選手の伸びしろやコーチング観点のご質問をお願いします。"
)
_SAFE_REFUSAL_EN = (
    "Sorry, I can't help with that. Please ask about player growth or "
    "coaching insights."
)


def _require_chat_role(ctx: AuthCtx) -> AuthCtx:
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="auth required")
    if ctx.role not in _ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="chat is restricted to coach/analyst/admin")
    if ctx.user_id is None:
        # admin 以外で user_id が無いケース (legacy X-Role) は許可しない
        raise HTTPException(status_code=401, detail="user_id required")
    return ctx


def _get_owned_session(db: Session, sid: int, ctx: AuthCtx) -> ChatSession:
    sess = db.query(ChatSession).filter(ChatSession.id == sid).first()
    if sess is None or sess.deleted_at is not None:
        raise HTTPException(status_code=404, detail="session not found")
    if not ctx.is_admin and sess.user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="not the owner of this session")
    return sess


def _serialize_message(m: ChatMessage) -> dict:
    return {
        "id": m.id,
        "turn": m.turn,
        "author": m.author,
        "content": m.content,
        "confidence": m.confidence,
        "evidence_path": m.evidence_path,
        "generator": m.generator,
        "is_fallback": bool(m.is_fallback),
        "validation_reason": m.validation_reason,
        "date_from": m.date_from,
        "date_to": m.date_to,
        "created_at": (m.created_at.isoformat() if m.created_at else None),
    }


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _build_analytics_context(
    db: Session,
    ctx: AuthCtx,
    sess: ChatSession,
    lang: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> dict:
    """チャット応答生成用の analytics スナップショット。

    Slice Y: build_player_summary() の compact LLM-ready 構造を直接利用する。
    coach/analyst/admin のみがチャットを使えるため raw payload を渡してよい。
    対象選手 ID が無い (player_id=0) ケースは空サマリ相当のフォールバック。
    """
    from backend.analysis.insights.player_summary_service import (
        build_player_summary,
    )

    player_id = ctx.player_id or 0
    if player_id <= 0:
        return {
            "player_id": 0,
            "sample": {"matches": 0, "rallies": 0, "strokes": 0},
            "outcomes": {"win_rate": 0.0, "set_win_rate": 0.0, "n": 0},
            "shot_mix": [],
            "zones": {"hit_top": [], "land_top": []},
            "conditions": {"avg_rpe": None, "avg_hooper": None, "n": 0},
            "recent_trend": {
                "last_5_match_win_rate": None,
                "delta_vs_prior_5": None,
            },
        }
    try:
        return build_player_summary(db, player_id, date_from, date_to, None)
    except Exception:
        return {
            "player_id": player_id,
            "sample": {"matches": 0, "rallies": 0, "strokes": 0},
        }


# ─── Schemas ─────────────────────────────────────────────────────────────
class _CreateSessionBody(BaseModel):
    lang: str = Field(default="ja", pattern="^(ja|en)$")


class _SendMessageBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    date_from: Optional[str] = Field(default=None)
    date_to: Optional[str] = Field(default=None)

    @field_validator("date_from", "date_to")
    @classmethod
    def _check_iso_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _ISO_DATE_RE.match(v):
            raise ValueError("must be YYYY-MM-DD")
        # 妥当性検証 (例えば 2025-02-30 を弾く)
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("invalid calendar date") from exc
        return v


# ─── Endpoints ───────────────────────────────────────────────────────────
@router.post("/insights/chat/sessions")
def create_chat_session(
    body: _CreateSessionBody,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    _require_chat_role(ctx)
    now = datetime.utcnow()
    sess = ChatSession(
        user_id=ctx.user_id,
        role_at_creation=ctx.role,
        lang=body.lang,
        created_at=now,
        last_used_at=now,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return {
        "session_id": sess.id,
        "lang": sess.lang,
        "created_at": sess.created_at.isoformat(),
    }


@router.get("/insights/chat/sessions/{sid}/messages")
def list_chat_messages(
    sid: int,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    _require_chat_role(ctx)
    _get_owned_session(db, sid, ctx)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == sid)
        .order_by(ChatMessage.turn.asc())
        .all()
    )
    return {"messages": [_serialize_message(m) for m in msgs]}


@router.post("/insights/chat/sessions/{sid}/messages")
def send_chat_message(
    sid: int,
    body: _SendMessageBody,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    _require_chat_role(ctx)
    sess = _get_owned_session(db, sid, ctx)

    # ── rate-limit ────────────────────────────────────────────────
    now_ts = time.monotonic()
    last_ts = _RATE_LIMIT.get(int(ctx.user_id))
    if last_ts is not None and (now_ts - last_ts) < _RATE_LIMIT_SECONDS:
        remaining = _RATE_LIMIT_SECONDS - (now_ts - last_ts)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "rate_limited",
                "retry_after_ms": int(remaining * 1000),
            },
        )

    # ── sanitize ──────────────────────────────────────────────────
    cleaned, flags = sanitize_user_input(body.content)
    injection = "injection_attempt" in flags

    # ── budget ────────────────────────────────────────────────────
    allowed, _remaining = check_and_record_budget(
        int(ctx.user_id), _APPROX_TOKENS_PER_MESSAGE
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": "budget_exceeded"},
        )

    # rate-limit 記録は budget check 通過後に行う
    _RATE_LIMIT[int(ctx.user_id)] = now_ts

    # ── next turn ─────────────────────────────────────────────────
    last_turn = (
        db.query(ChatMessage.turn)
        .filter(ChatMessage.session_id == sid)
        .order_by(ChatMessage.turn.desc())
        .first()
    )
    next_turn = (last_turn[0] + 1) if last_turn else 1

    # ── user message を永続化 ─────────────────────────────────────
    user_msg = ChatMessage(
        session_id=sid,
        turn=next_turn,
        author="user",
        content=cleaned,
        tokens=_APPROX_TOKENS_PER_MESSAGE // 2,
        validation_reason=("injection_attempt" if injection else None),
        date_from=body.date_from,
        date_to=body.date_to,
    )
    db.add(user_msg)
    db.flush()

    # ── AI 応答生成 ────────────────────────────────────────────────
    if injection:
        # 安全な定型応答 (LLM を呼ばない)
        safe_text = _SAFE_REFUSAL_JA if sess.lang == "ja" else _SAFE_REFUSAL_EN
        ai_msg = ChatMessage(
            session_id=sid,
            turn=next_turn + 1,
            author="system",
            content=safe_text,
            tokens=0,
            generator=None,
            is_fallback=True,
            validation_reason="injection_attempt",
            confidence=None,
            evidence_path=None,
        )
    else:
        analytics = _build_analytics_context(
            db, ctx, sess, sess.lang,
            date_from=body.date_from, date_to=body.date_to,
        )
        insight_ctx: InsightContext = {
            "player_id": 0,
            "period_days": 30,
            "analytics": analytics,
            "role": ctx.role,
            "lang": sess.lang,
        }
        try:
            result = get_generator().generate(insight_ctx)
        except Exception as exc:  # noqa: BLE001
            # ハーネス未経由でも常に template を最終フォールバックに
            from backend.analysis.insights.template import TemplateGenerator
            result = TemplateGenerator().generate(insight_ctx)
            result_meta = {"fallback_reason": f"generate_exception:{type(exc).__name__}"}
        else:
            result_meta = dict(result.get("meta") or {}) if isinstance(result, dict) else {}

        items = result.get("items") or []
        if items:
            first = items[0]
            ai_text = first.get("prose") or ""
            confidence = first.get("confidence")
            evidence_path = first.get("evidence_path")
        else:
            ai_text = (
                "現時点では十分なデータがないため、まずは試合数を積み重ねてみましょう。"
                if sess.lang == "ja"
                else "Not enough data yet — keep logging matches to unlock insights."
            )
            confidence = None
            evidence_path = None

        fallback_reason = result_meta.get("fallback_reason")
        ai_msg = ChatMessage(
            session_id=sid,
            turn=next_turn + 1,
            author="ai",
            content=ai_text,
            tokens=_APPROX_TOKENS_PER_MESSAGE // 2,
            generator=result.get("generator"),
            is_fallback=bool(fallback_reason),
            validation_reason=fallback_reason,
            confidence=confidence,
            evidence_path=evidence_path,
        )

    db.add(ai_msg)
    sess.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(ai_msg)

    return {
        "user_message": _serialize_message(user_msg),
        "ai_message": _serialize_message(ai_msg),
    }


@router.delete("/insights/chat/sessions/{sid}")
def delete_chat_session(
    sid: int,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    _require_chat_role(ctx)
    sess = _get_owned_session(db, sid, ctx)
    sess.deleted_at = datetime.utcnow()
    # privacy: メッセージ本文を匿名化
    db.query(ChatMessage).filter(ChatMessage.session_id == sid).update(
        {ChatMessage.content: "(reset)"},
        synchronize_session=False,
    )
    db.commit()
    return {"success": True}
