"""汎用 LLM チャット API (/#/llm)。

アクセス制御: admin、または admin が `llm` page_access を付与したユーザのみ
(`require_llm_access`)。会話は所有者 (or admin) のみ (IDOR 防止)。バドミントン特化
insights chat (insights_chat.py) とは完全に別系統。

- GET    /api/llm/config                       : プロバイダ/モデル + 利用可否
- GET    /api/llm/conversations                : 自分の会話一覧
- POST   /api/llm/conversations                : 会話作成
- DELETE /api/llm/conversations/{cid}          : 会話削除 (soft)
- GET    /api/llm/conversations/{cid}/messages : ターン一覧
- POST   /api/llm/conversations/{cid}/messages : 送信 + SSE ストリーミング応答
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal, get_db
from backend.db.models import LlmConversation, LlmTurn, PlayerPageAccess
from backend.services.llm import get_provider
from backend.services.llm.base import ChatMessage
from backend.services.llm.registry import provider_configured
from backend.utils.access_log import log_access
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_CONTEXT_TURNS = 30
MAX_TOKENS = 2048
_RATE_LIMIT_SEC = 1.0
_last_req: dict = {}


def require_llm_access(request: Request, db: Session):
    """admin か、`llm` page_access を持つユーザのみ通す。フロントゲートに依存しない
    サーバ側強制 (LLM 専用ユーザがバドミントン側へ回り込めないのと同様の境界)。"""
    ctx = get_auth(request)
    if ctx.role is None or ctx.user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if ctx.is_admin:
        return ctx
    # user 単位 grant は user_id 一致のみ。team 単位 grant は本人が team を持つ時だけ評価する。
    # (team_name==None の OR で全 user-level grant に当たる NULL マッチ漏洩を防ぐ)
    conds = [PlayerPageAccess.user_id == ctx.user_id]
    if ctx.team_name:
        conds.append(PlayerPageAccess.team_name == ctx.team_name)
    has = (
        db.query(PlayerPageAccess)
        .filter(PlayerPageAccess.page_key == "llm", or_(*conds))
        .first()
    )
    if not has:
        raise HTTPException(status_code=403, detail="LLM access not granted")
    return ctx


def _own_conversation(cid: int, ctx, db: Session) -> LlmConversation:
    c = db.get(LlmConversation, cid)
    if not c or c.deleted_at is not None or (c.user_id != ctx.user_id and not ctx.is_admin):
        raise HTTPException(status_code=404, detail="conversation not found")
    return c


def _conv_dict(c: LlmConversation) -> dict:
    return {
        "id": c.id, "title": c.title, "provider": c.provider, "model": c.model,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
    }


def _turn_dict(t: LlmTurn) -> dict:
    return {"id": t.id, "seq": t.seq, "role": t.role, "content": t.content,
            "created_at": t.created_at.isoformat() if t.created_at else None}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


class ConversationCreate(BaseModel):
    model_config = {"extra": "forbid"}  # mass-assignment 防止
    title: Optional[str] = Field(default=None, max_length=200)
    system_prompt: Optional[str] = Field(default=None, max_length=8000)


class MessageCreate(BaseModel):
    model_config = {"extra": "forbid"}  # mass-assignment 防止
    content: str = Field(min_length=1, max_length=16000)


@router.get("/llm/config")
def llm_config(request: Request, db: Session = Depends(get_db)):
    require_llm_access(request, db)
    pr = get_provider()
    return {"provider": pr.name.split(":")[0], "model": pr.model,
            "configured": provider_configured(), "streaming": True}


@router.get("/llm/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    rows = (
        db.query(LlmConversation)
        .filter(LlmConversation.user_id == ctx.user_id, LlmConversation.deleted_at == None)  # noqa: E711
        .order_by(LlmConversation.last_used_at.desc())
        .limit(100).all()
    )
    return {"conversations": [_conv_dict(c) for c in rows]}


@router.post("/llm/conversations", status_code=201)
def create_conversation(body: ConversationCreate, request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    pr = get_provider()
    c = LlmConversation(
        user_id=ctx.user_id, title=(body.title or "新しいチャット"),
        provider=pr.name.split(":")[0], model=pr.model, system_prompt=body.system_prompt,
    )
    db.add(c); db.commit(); db.refresh(c)
    log_access(db, "llm_conversation_create", user_id=ctx.user_id,
               resource_type="llm_conversation", resource_id=c.id)
    return _conv_dict(c)


@router.delete("/llm/conversations/{cid}")
def delete_conversation(cid: int, request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    c = _own_conversation(cid, ctx, db)
    c.deleted_at = datetime.utcnow(); db.commit()
    log_access(db, "llm_conversation_delete", user_id=ctx.user_id,
               resource_type="llm_conversation", resource_id=c.id)
    return {"success": True}


@router.get("/llm/conversations/{cid}/messages")
def list_messages(cid: int, request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    c = _own_conversation(cid, ctx, db)
    turns = db.query(LlmTurn).filter(LlmTurn.conversation_id == c.id).order_by(LlmTurn.seq.asc()).all()
    return {"messages": [_turn_dict(t) for t in turns]}


@router.post("/llm/conversations/{cid}/messages")
def post_message(cid: int, body: MessageCreate, request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    c = _own_conversation(cid, ctx, db)

    now = time.monotonic()
    if now - _last_req.get(ctx.user_id, 0.0) < _RATE_LIMIT_SEC:
        raise HTTPException(status_code=429, detail="slow down")
    _last_req[ctx.user_id] = now
    if not provider_configured():
        raise HTTPException(status_code=503, detail="LLM provider not configured")

    last_seq = db.query(func.max(LlmTurn.seq)).filter(LlmTurn.conversation_id == c.id).scalar() or 0
    db.add(LlmTurn(conversation_id=c.id, seq=last_seq + 1, role="user", content=body.content))
    c.last_used_at = datetime.utcnow()
    db.commit()
    log_access(db, "llm_message", user_id=ctx.user_id,
               resource_type="llm_conversation", resource_id=c.id,
               details={"chars": len(body.content)})

    turns = db.query(LlmTurn).filter(LlmTurn.conversation_id == c.id).order_by(LlmTurn.seq.asc()).all()
    history = [ChatMessage(role=t.role, content=t.content)
               for t in turns if t.role in ("user", "assistant", "system")][-MAX_CONTEXT_TURNS:]
    system_prompt = c.system_prompt
    provider_name, model, conv_id, assistant_seq = c.provider, c.model, c.id, last_seq + 2

    def gen():
        acc = []
        try:
            pr = get_provider(provider=provider_name, model=model)
            yield _sse({"type": "start", "model": pr.model})
            for d in pr.stream_chat(history, system=system_prompt, max_tokens=MAX_TOKENS):
                if d.content:
                    acc.append(d.content)
                    yield _sse({"type": "delta", "content": d.content})
            yield _sse({"type": "done"})
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm stream failed: %s", exc)
            yield _sse({"type": "error", "message": "生成中にエラーが発生しました"})
        finally:
            text = "".join(acc)
            if text:
                try:
                    with SessionLocal() as s2:
                        s2.add(LlmTurn(conversation_id=conv_id, seq=assistant_seq,
                                       role="assistant", content=text, tokens=len(text) // 4))
                        s2.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("persist assistant turn failed: %s", exc)

    return StreamingResponse(gen(), media_type="text/event-stream")
