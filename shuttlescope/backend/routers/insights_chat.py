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
from backend.analysis.chat.slot_extractors import extract_all
from backend.analysis.chat.scope_merger import merge_scope, clear_signals


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
        # 2026-05-25: datetime.utcnow() の naive ISO だとフロントが local 扱いするので
        #   "Z" を付与して UTC を明示。フロントは toLocaleTimeString でブラウザの
        #   タイムゾーンに変換する。
        "created_at": (m.created_at.isoformat() + "Z" if m.created_at else None),
    }


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _build_analytics_context(
    db: Session,
    ctx: AuthCtx,
    sess: ChatSession,
    lang: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    target_player_id: Optional[int] = None,
) -> dict:
    """チャット応答生成用の analytics スナップショット。

    Slice Y: build_player_summary() の compact LLM-ready 構造を直接利用する。
    coach/analyst/admin のみがチャットを使えるため raw payload を渡してよい。
    対象選手 ID が無い (player_id=0) ケースは空サマリ相当のフォールバック。

    target_player_id:
        admin/coach/analyst が dashboard で観察中の他選手を指定するための override。
        指定された場合は ctx.player_id ではなく target_player_id を使う。
        ロール gate は send_message ハンドラで行うのでここでは呼ばれた時点で許可済前提。
    """
    from backend.analysis.insights.player_summary_service import (
        build_player_summary,
    )

    player_id = int(target_player_id) if (target_player_id and target_player_id > 0) else (ctx.player_id or 0)
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
    # 会話スコープ拡張: クライアント側 (composer chip UI) で確定済みの slot 値
    shot_type: Optional[str] = Field(default=None)
    zone: Optional[str] = Field(default=None)
    # ユーザが明示的にクリアしたスロット名 (e.g. ["period", "zone"])
    clear_slots: Optional[list[str]] = Field(default=None)
    # ダッシュボードで観察中の対象選手 ID。admin/coach/analyst が他選手を見ているときに
    # frontend が現在の viewed playerId を渡す。admin/coach/analyst 以外の role が
    # 指定しても無視 (ctx.player_id fallback)。player ロール自身は自分の id 以外
    # 渡せない (cross-player snooping 防止)。
    target_player_id: Optional[int] = Field(default=None, ge=0)

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
        "created_at": sess.created_at.isoformat() + "Z",
    }


@router.get("/insights/chat/sessions/{sid}/messages")
def list_chat_messages(
    sid: int,
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
) -> dict:
    _require_chat_role(ctx)
    sess = _get_owned_session(db, sid, ctx)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == sid)
        .order_by(ChatMessage.turn.asc())
        .all()
    )
    scope = sess.current_scope if isinstance(sess.current_scope, dict) else None
    applied_scope = {
        "period": (scope or {}).get("period"),
        "shot_type": (scope or {}).get("shot_type"),
        "zone": (scope or {}).get("zone"),
    } if scope else None
    return {
        "messages": [_serialize_message(m) for m in msgs],
        "applied_scope": applied_scope,
    }


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

    # ── 会話スコープのマージ ───────────────────────────────────────
    # 1) サーバ側 rule-based 抽出
    extracted = extract_all(cleaned, datetime.utcnow())
    # 2) クライアント側で確定済みの slot 値が来た場合はそちらを優先
    client_deltas: dict = {}
    if body.date_from or body.date_to:
        client_deltas["period"] = {
            "date_from": body.date_from,
            "date_to": body.date_to,
            "label": f"{body.date_from or '…'} → {body.date_to or 'today'}",
        }
    if body.shot_type:
        client_deltas["shot_type"] = {"code": body.shot_type, "label": body.shot_type}
    if body.zone:
        client_deltas["zone"] = {"code": body.zone, "label": body.zone}

    # 3) 明示 clear 判定 (テキスト + クライアントから来た clear_slots)
    text_clears = clear_signals(cleaned)
    clear_all_signal = "__all__" in text_clears
    explicit_clear_slots = sorted(
        (set(body.clear_slots or []) | (text_clears - {"__all__"}))
    )

    # merge: extracted < client (last-write-wins)
    deltas = {**extracted, **client_deltas}
    if clear_all_signal:
        deltas["clear_all_scope"] = True
    if explicit_clear_slots:
        deltas["clear_slots"] = explicit_clear_slots

    prev_scope = sess.current_scope if isinstance(sess.current_scope, dict) else None
    new_scope = merge_scope(
        prev_scope,
        deltas,
        turn=next_turn,
        source=("client" if client_deltas else "extracted"),
    )
    sess.current_scope = new_scope

    # period を最終解決値として下流に流す (scope 優先, body fallback)
    eff_period = new_scope.get("period") or {}
    eff_date_from = eff_period.get("date_from") if isinstance(eff_period, dict) else None
    eff_date_to = eff_period.get("date_to") if isinstance(eff_period, dict) else None

    # ── user message を永続化 ─────────────────────────────────────
    user_msg = ChatMessage(
        session_id=sid,
        turn=next_turn,
        author="user",
        content=cleaned,
        tokens=_APPROX_TOKENS_PER_MESSAGE // 2,
        validation_reason=("injection_attempt" if injection else None),
        date_from=eff_date_from,
        date_to=eff_date_to,
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
        # target_player_id role-gate: admin/coach/analyst のみ override 可
        effective_target = None
        if body.target_player_id and body.target_player_id > 0:
            if ctx.role in ("admin", "coach", "analyst"):
                effective_target = int(body.target_player_id)
            # それ以外の role は黙って無視 (cross-player snooping 防止)
        analytics = _build_analytics_context(
            db, ctx, sess, sess.lang,
            date_from=eff_date_from, date_to=eff_date_to,
            target_player_id=effective_target,
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
            # 「何を送っても同じ canned response が返ってくる」状態を防ぐ。
            # 実 sample 数 + 必要 N を明示し、ユーザ入力を echo して
            # 「メッセージは届いているがインサイト生成に必要なデータが
            # まだ足りない」ことを誠実に伝える。
            sample = (analytics or {}).get("sample") or {}
            n_match = int(sample.get("matches", 0) or 0)
            n_rally = int(sample.get("rallies", 0) or 0)
            min_rally = 30
            quote = cleaned.strip()[:80]
            if quote and sess.lang == "ja":
                ai_text = (
                    f"ご質問「{quote}」を受け取りました。\n"
                    f"現在 DB には {n_match} 試合 / {n_rally} ラリーが登録されています。"
                    f"信頼できるインサイトを出すには最低 {min_rally} ラリー必要です。"
                )
            elif quote:
                ai_text = (
                    f"Got your question: \"{quote}\".\n"
                    f"DB currently holds {n_match} matches / {n_rally} rallies. "
                    f"We need at least {min_rally} rallies to surface reliable insights."
                )
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

    # applied_scope は frontend で "Active filters" バーを描画するために返す
    applied_scope = {
        "period": new_scope.get("period"),
        "shot_type": new_scope.get("shot_type"),
        "zone": new_scope.get("zone"),
    }
    user_payload = _serialize_message(user_msg)
    if isinstance(new_scope.get("shot_type"), dict):
        user_payload["shot_type"] = new_scope["shot_type"].get("code")
    if isinstance(new_scope.get("zone"), dict):
        user_payload["zone"] = new_scope["zone"].get("code")
    return {
        "user_message": user_payload,
        "ai_message": _serialize_message(ai_msg),
        "applied_scope": applied_scope,
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
