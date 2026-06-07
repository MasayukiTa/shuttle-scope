"""汎用 LLM チャット API (/#/llm)。

アクセス制御: admin、または admin が `llm` page_access を付与したユーザのみ
(`require_llm_access`)。会話は所有者 (or admin) のみ (IDOR 防止)。バドミントン特化
insights chat (insights_chat.py) とは完全に別系統。

- GET    /api/llm/config                       : プロバイダ/モデル + 利用可否
- GET    /api/llm/conversations                : 自分の会話一覧
- POST   /api/llm/conversations                : 会話作成
- PATCH  /api/llm/conversations/{cid}          : 会話タイトル変更 (所有者のみ)
- DELETE /api/llm/conversations/{cid}          : 会話削除 (soft)
- GET    /api/llm/conversations/{cid}/messages : ターン一覧
- POST   /api/llm/conversations/{cid}/messages : 送信 + SSE ストリーミング応答
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import time
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.db.database import SessionLocal, get_db
from backend.db.models import LlmConversation, LlmTurn, PlayerPageAccess
from backend.services.llm import get_provider
from backend.services.llm.base import ChatMessage
from backend.services.llm.registry import (
    provider_configured,
    reasoning_available,
    reasoning_model,
    tools_available,
    vision_available,
)
from backend.services.llm.tools import tool_definitions
from backend.utils.access_log import log_access
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_CONTEXT_TURNS = 40
MAX_TOKENS = 2048
CONTEXT_TOKEN_BUDGET = 8000      # 履歴に使うトークン上限 (context rot / 上限超過回避)
_RATE_LIMIT_SEC = 1.0
_last_req: dict = {}

# ── 画像 (マルチモーダル) 入力の上限 ─────────────────────────────────────────
MAX_IMAGES = 4                          # 1 メッセージあたりの画像枚数上限
MAX_IMAGE_BYTES = 6 * 1024 * 1024       # 1 枚あたりのデコード後サイズ上限 (~6MB)
ALLOWED_IMAGE_MIMES = ("image/png", "image/jpeg", "image/webp", "image/gif")
# data:image/<mime>;base64,<payload> 形式のみ受理 (URL 直 fetch は SSRF 回避のため不可)。
_DATA_URL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)


def _validate_images(images: List[str]) -> List[dict]:
    """base64 data URL のリストを検証し、画像ごとのメタ (mime/bytes) を返す。

    不正 (枚数超過 / 非対応 mime / サイズ超過 / base64 破損 / 非 data URL) は 422。
    full base64 は返さず、DB へ保存するのはこのメタ (枚数・mime・サイズ) のみ。"""
    if not images:
        return []
    if len(images) > MAX_IMAGES:
        raise HTTPException(status_code=422,
                            detail=f"画像は最大 {MAX_IMAGES} 枚までです")
    metas: List[dict] = []
    for i, item in enumerate(images):
        if not isinstance(item, str):
            raise HTTPException(status_code=422, detail=f"画像 {i + 1} の形式が不正です")
        m = _DATA_URL_RE.match(item.strip())
        if not m:
            raise HTTPException(status_code=422,
                                detail=f"画像 {i + 1} は data URL (base64) で指定してください")
        mime = m.group(1).lower()
        if mime not in ALLOWED_IMAGE_MIMES:
            raise HTTPException(status_code=422,
                                detail=f"画像 {i + 1} の形式 ({mime}) は未対応です "
                                       "(png/jpeg/webp/gif のみ)")
        b64 = m.group(2).strip()
        # validate=True で非 base64 文字が混入していれば例外 → 422 に変換。
        try:
            raw = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422,
                                detail=f"画像 {i + 1} の base64 が破損しています")
        if not raw:
            raise HTTPException(status_code=422, detail=f"画像 {i + 1} が空です")
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=422,
                                detail=f"画像 {i + 1} が大きすぎます "
                                       f"(上限 {MAX_IMAGE_BYTES // (1024 * 1024)}MB)")
        metas.append({"mime": mime, "bytes": len(raw)})
    return metas


def _build_multimodal_content(text: str, images: List[str]):
    """OpenAI 互換のマルチモーダル content 配列を作る。

    content = [{"type":"text","text":...},
               {"type":"image_url","image_url":{"url": dataurl}}, ...]
    画像が無ければ呼び出し側で素の文字列を使う (この関数は画像ありの時のみ)。"""
    parts: List[dict] = []
    if text:
        parts.append({"type": "text", "text": text})
    for dataurl in images:
        parts.append({"type": "image_url", "image_url": {"url": dataurl.strip()}})
    return parts


def _est_tokens(s: str) -> int:
    return max(1, len(s or "") // 4)


def _windowed_history(turns) -> list:
    """会話メモリ: その会話のターンのみを、直近からトークン予算/件数上限まで詰める。
    他ユーザ・他会話のメッセージは構造上一切混入しない (turns は conversation_id 固定)。"""
    msgs = [ChatMessage(role=t.role, content=t.content)
            for t in turns if t.role in ("user", "assistant", "system")]
    out, used = [], 0
    for m in reversed(msgs):
        tok = _est_tokens(m.content)
        if out and (used + tok > CONTEXT_TOKEN_BUDGET or len(out) >= MAX_CONTEXT_TURNS):
            break
        out.append(m); used += tok
    out.reverse()
    return out


def require_llm_access(request: Request, db: Session):
    """admin か、`llm` page_access を持つユーザのみ通す。フロントゲートに依存しない
    サーバ側強制 (LLM 専用ユーザがバドミントン側へ回り込めないのと同様の境界)。"""
    ctx = get_auth(request)
    if ctx.role is None or ctx.user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    # admin と 'llm' ロールは LLM アクセスを role で事前付与 (per-user grant 不要)。
    if ctx.is_admin or ctx.role == "llm":
        return ctx
    # それ以外のロール (analyst/coach 等) は admin が付与した 'llm' page grant が必要。
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
    # 厳格な所有者限定: 会話の中身は本人のみ (admin でも他人のチャットは読めない=混在/privacy 防止)。
    # admin は user/grant 管理はできるが、ユーザの会話内容にはアクセスしない。
    c = db.get(LlmConversation, cid)
    if not c or c.deleted_at is not None or c.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="conversation not found")
    return c


def _conv_dict(c: LlmConversation) -> dict:
    # provider / model は非開示: UI にも API レスポンスにも出さない (DB 列としては保持)。
    return {
        "id": c.id, "title": c.title,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
    }


def _turn_dict(t: LlmTurn) -> dict:
    d = {"id": t.id, "seq": t.seq, "role": t.role, "content": t.content,
         "created_at": t.created_at.isoformat() if t.created_at else None}
    # 画像メタは tool_calls JSON 列に _images として保持 (full base64 は保存しない)。
    # フロントには枚数のみ surface (UI で「画像 N 枚添付」表示用)。
    meta = t.tool_calls if isinstance(t.tool_calls, dict) else None
    if meta and isinstance(meta.get("_images"), dict):
        d["image_count"] = int(meta["_images"].get("count") or 0)
    return d


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


class ConversationCreate(BaseModel):
    model_config = {"extra": "forbid"}  # mass-assignment 防止
    title: Optional[str] = Field(default=None, max_length=200)
    system_prompt: Optional[str] = Field(default=None, max_length=8000)


class MessageCreate(BaseModel):
    model_config = {"extra": "forbid"}  # mass-assignment 防止
    content: str = Field(min_length=1, max_length=16000)
    # 『深く考えるモード』: True なら reasoning モデル (LLM_REASONING_MODEL) で応答する。
    thinking: bool = False
    # マルチモーダル: 各要素は base64 data URL ("data:image/png;base64,...")。
    # 枚数/サイズ/mime は _validate_images で検証。vision 未対応モデルでは送信を拒否。
    images: List[str] = Field(default_factory=list)


class ConversationRename(BaseModel):
    model_config = {"extra": "forbid"}  # mass-assignment 防止
    title: str = Field(min_length=1, max_length=200)


@router.get("/llm/config")
def llm_config(request: Request, db: Session = Depends(get_db)):
    require_llm_access(request, db)
    # モデル/プロバイダ名は非開示。利用可否と各機能トグルの可否のみ返す。
    return {"configured": provider_configured(), "streaming": True,
            "reasoning_available": reasoning_available(),
            "vision_available": vision_available(),
            "tools_available": tools_available()}


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


@router.patch("/llm/conversations/{cid}")
def rename_conversation(cid: int, body: ConversationRename, request: Request, db: Session = Depends(get_db)):
    ctx = require_llm_access(request, db)
    c = _own_conversation(cid, ctx, db)  # 所有者限定 (IDOR 防止)
    c.title = body.title.strip()[:200]
    db.commit(); db.refresh(c)
    log_access(db, "llm_conversation_rename", user_id=ctx.user_id,
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

    # 画像検証は副作用 (rate-limit / DB 書き込み) より前に行い、不正なら 422 で即返す。
    image_metas = _validate_images(body.images)
    if image_metas and not vision_available():
        # vision 未対応モデルへ画像を送ろうとした場合は明示拒否 (silent drop しない)。
        raise HTTPException(status_code=422, detail="画像はこのモデルでは未対応です")

    now = time.monotonic()
    if now - _last_req.get(ctx.user_id, 0.0) < _RATE_LIMIT_SEC:
        raise HTTPException(status_code=429, detail="slow down")
    _last_req[ctx.user_id] = now
    if not provider_configured():
        raise HTTPException(status_code=503, detail="LLM provider not configured")

    # 画像メタ (枚数/mime/合計バイト) のみ tool_calls JSON 列へ保存。full base64 は保存しない
    # (DB / WAL / backup の肥大化を避ける)。
    user_meta = None
    if image_metas:
        user_meta = {"_images": {
            "count": len(image_metas),
            "mimes": [m["mime"] for m in image_metas],
            "bytes": sum(m["bytes"] for m in image_metas),
        }}

    last_seq = db.query(func.max(LlmTurn.seq)).filter(LlmTurn.conversation_id == c.id).scalar() or 0
    db.add(LlmTurn(conversation_id=c.id, seq=last_seq + 1, role="user",
                   content=body.content, tool_calls=user_meta))
    c.last_used_at = datetime.utcnow()
    # 自動タイトル: 最初のユーザ発言から (既存製品同様)。
    if last_seq == 0 and (not c.title or c.title == "新しいチャット"):
        c.title = (body.content.strip()[:40] or "新しいチャット")
    db.commit()
    log_access(db, "llm_message", user_id=ctx.user_id,
               resource_type="llm_conversation", resource_id=c.id,
               details={"chars": len(body.content), "images": len(image_metas)})

    # メモリ: この会話のターンのみをトークン予算でウィンドウ化 (他会話/他ユーザは構造上混入しない)。
    turns = db.query(LlmTurn).filter(LlmTurn.conversation_id == c.id).order_by(LlmTurn.seq.asc()).all()
    history = _windowed_history(turns)
    # 画像があれば、最後の user メッセージ (今回送信分) のみをマルチモーダル content 配列に
    # 差し替える。履歴 (過去ターン) は base64 を保持していないため文字列のまま。
    if image_metas and history:
        for m in reversed(history):
            if m.role == "user":
                m.content = _build_multimodal_content(body.content, body.images)
                break
    system_prompt = c.system_prompt
    # 『深く考えるモード』: thinking 指定かつ reasoning モデルが設定済みなら、会話の通常
    # モデルではなく reasoning モデル (LLM_REASONING_MODEL) を使う。未設定なら通常モデル。
    use_reasoning = bool(body.thinking) and reasoning_available()
    model = reasoning_model() if use_reasoning else c.model
    provider_name, conv_id, assistant_seq = c.provider, c.id, last_seq + 2
    # tools: 機構が無効/有効ツール無しなら None → payload に tools を入れない (既存挙動と同一)。
    tools = tool_definitions()

    def gen():
        acc = []
        try:
            pr = get_provider(provider=provider_name, model=model)
            # start: モデル名は非開示。reasoning モードか否かだけを伝える。
            yield _sse({"type": "start", "thinking": use_reasoning})
            for d in pr.stream_chat(history, system=system_prompt, tools=tools,
                                    max_tokens=MAX_TOKENS):
                # reasoning モデルの思考過程 (CoT) はライブ表示のみ。履歴には保存しない
                # (DeepSeek 等は reasoning_content を後続リクエストに含めてはならない仕様)。
                if d.reasoning:
                    yield _sse({"type": "reasoning", "content": d.reasoning})
                if d.content:
                    acc.append(d.content)
                    yield _sse({"type": "delta", "content": d.content})
                # tool_call: ツール機構が有効でモデルが関数呼び出しを要求した時のみ届く
                # (既定では None なので発火しない = 既存の SSE イベント形状は不変)。
                # 将来のツール実行ループはここで蓄積→実行→再投入する土台。
                if d.tool_call:
                    yield _sse({"type": "tool_call", "tool_call": d.tool_call})
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
