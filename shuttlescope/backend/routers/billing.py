"""Phase Pay-1: 課金 / 決済 API ルーター。

全エンドポイントは include_in_schema=False で OpenAPI / Swagger から非公開。
SS_BILLING_ENABLED=0 の間は 503 を返す (注文 / 商品 / 権利系)。
Webhook は SS_BILLING_ENABLED に関係なく受信可能 (プロバイダ側のテストイベント受信用)。

エンドポイント (パスは /api/_internal/billing/...):
  POST   /orders                      注文作成 + 決済セッション生成
  GET    /orders/{public_id}          注文状態取得 (本人 / admin)
  POST   /orders/{public_id}/cancel   注文キャンセル
  POST   /webhooks/stripe             Stripe Webhook (no-auth, 署名検証)
  POST   /webhooks/komoju             KOMOJU Webhook (no-auth, 署名検証)
  POST   /webhooks/univapay           Univapay Webhook (no-auth, 署名検証)
  GET    /entitlements                自分の権利一覧
  GET    /admin/orders                admin only: 全注文一覧
  GET    /admin/products              admin only: 商品マスタ
  POST   /admin/products              admin only: 商品追加
  POST   /admin/refund/{order_id}     admin only: 返金処理
  POST   /admin/grant_entitlement     admin only: 手動権利付与
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import (
    BillingProduct, BillingOrder, BillingWebhookEvent, BillingEntitlement, User,
)
from backend.services.billing import (
    is_billing_enabled, get_provider_for_method, get_provider_by_name,
    PAYMENT_METHOD_ROUTING, SUPPORTED_PAYMENT_METHODS,
)
from backend.utils.access_log import log_access
from backend.utils.auth import get_auth

logger = logging.getLogger(__name__)

# include_in_schema=False で OpenAPI / Swagger 非公開
router = APIRouter(prefix="/_internal/billing", tags=["billing-internal"], include_in_schema=False)


# ─── ヘルパー ──────────────────────────────────────────────────────────

def _require_billing_enabled():
    if not is_billing_enabled():
        raise HTTPException(
            status_code=503,
            detail="課金機能は現在無効化されています (Phase Pay-1: 試験運用中)",
        )


def _require_login(request: Request):
    ctx = get_auth(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    return ctx


def _require_admin(request: Request):
    ctx = _require_login(request)
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin ロールが必要です")
    return ctx


def _client_ip(request: Request) -> str:
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf[:64]
    return (request.client.host if request.client else "")[:64]


def _serialize_order(o: BillingOrder, *, for_admin: bool = False) -> dict:
    out = {
        "public_id": o.public_id,
        "amount_jpy": o.amount_jpy,
        "currency": o.currency,
        "status": o.status,
        "payment_method": o.payment_method,
        "provider": o.provider,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "paid_at": o.paid_at.isoformat() if o.paid_at else None,
    }
    if for_admin:
        out.update({
            "id": o.id,
            "user_id": o.user_id,
            "product_id": o.product_id,
            "provider_session_id": o.provider_session_id,
            "provider_payment_id": o.provider_payment_id,
            "extra_metadata": o.extra_metadata,
        })
    return out


# ─── スキーマ ─────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=50)
    payment_method: str = Field(..., min_length=1, max_length=30)
    extra_metadata: Optional[dict] = None  # match_id 等を埋め込む


class CreateProductRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    price_jpy: int = Field(..., ge=1, le=10_000_000)
    is_active: bool = True


class GrantEntitlementRequest(BaseModel):
    user_id: int = Field(..., ge=1, le=2_147_483_647)
    entitlement_type: str = Field(..., min_length=1, max_length=50)
    resource_type: Optional[str] = Field(None, max_length=50)
    resource_id: Optional[int] = Field(None, ge=1, le=2_147_483_647)
    valid_to_iso: Optional[str] = None
    note: Optional[str] = Field(None, max_length=500)


# ─── 0. 法的情報 (env から取得して返す、フロント特商法ページ用) ───────

@router.get("/legal_info")
def get_legal_info(request: Request):
    """事業者情報を返す。値は全て env (settings) から取得、コードに固定値なし。

    SS_BILLING_ENABLED に関係なく取得可能 (法的に常時表示が必要なため)。
    認証も不要 (公開情報)。
    """
    from backend.config import settings as _s
    return {
        "success": True,
        "data": {
            "company_name": getattr(_s, "ss_legal_company_name", "") or "",
            "representative": getattr(_s, "ss_legal_representative", "") or "",
            "address": getattr(_s, "ss_legal_address", "") or "",
            "phone": getattr(_s, "ss_legal_phone", "") or "",
            "phone_disclosure_policy": getattr(_s, "ss_legal_phone_disclosure_policy", "") or "",
            "email": getattr(_s, "ss_legal_email", "") or "support@shuttle-scope.com",
            "business_hours": getattr(_s, "ss_legal_business_hours", "") or "",
            "extra_fees": getattr(_s, "ss_legal_extra_fees", "") or "",
            "payment_timing": getattr(_s, "ss_legal_payment_timing", "") or "",
            "delivery_timing": getattr(_s, "ss_legal_delivery_timing", "") or "",
            "refund_policy": getattr(_s, "ss_legal_refund_policy", "") or "",
            "invoice_registration_number": getattr(_s, "ss_invoice_registration_number", "") or "",
            "consumption_tax_rate": float(getattr(_s, "ss_consumption_tax_rate", 0.10)),
            "billing_enabled": is_billing_enabled(),
        },
    }


# ─── 1. 注文 ─────────────────────────────────────────────────────────

@router.post("/orders")
def create_order(body: CreateOrderRequest, request: Request, db: Session = Depends(get_db)):
    """注文を作成し、決済プロバイダのセッション URL を返す。"""
    _require_billing_enabled()
    ctx = _require_login(request)

    # 商品マスタから価格取得 (クライアント送信価格は信用しない)
    product = (
        db.query(BillingProduct)
        .filter(BillingProduct.code == body.product_code, BillingProduct.is_active.is_(True))
        .first()
    )
    if product is None:
        raise HTTPException(status_code=404, detail="商品が見つかりません")

    if body.payment_method not in PAYMENT_METHOD_ROUTING:
        raise HTTPException(
            status_code=422,
            detail=f"対応していない決済手段: {body.payment_method}. "
                   f"対応: {SUPPORTED_PAYMENT_METHODS}",
        )

    provider_name = PAYMENT_METHOD_ROUTING[body.payment_method]
    provider = get_provider_for_method(body.payment_method)

    # 注文レコード作成 (status=pending)
    from backend.config import settings
    return_url = (getattr(settings, "ss_billing_return_url", "") or "").strip() \
        or "https://app.shuttle-scope.com/billing/done"
    cancel_url = (getattr(settings, "ss_billing_cancel_url", "") or "").strip() \
        or "https://app.shuttle-scope.com/billing/cancel"

    order = BillingOrder(
        public_id=_uuid.uuid4().hex + "-" + _uuid.uuid4().hex[:4],  # 安全のため長め
        user_id=ctx.user_id,
        product_id=product.id,
        amount_jpy=product.price_jpy,
        currency="JPY",
        status="pending",
        payment_method=body.payment_method,
        provider=provider_name,
        extra_metadata=json.dumps(body.extra_metadata) if body.extra_metadata else None,
        return_url=return_url,
        cancel_url=cancel_url,
    )
    db.add(order)
    db.flush()  # id 確定

    # プロバイダ側でセッション作成
    customer_email = None
    user = db.get(User, ctx.user_id)
    if user is not None:
        customer_email = getattr(user, "email", None)
    try:
        session = provider.create_session(
            order_public_id=order.public_id,
            amount_jpy=order.amount_jpy,
            product_name=product.name,
            payment_method=body.payment_method,
            return_url=return_url,
            cancel_url=cancel_url,
            customer_email=customer_email,
        )
    except NotImplementedError as exc:
        db.rollback()
        raise HTTPException(status_code=501, detail=f"プロバイダ未実装: {exc}")
    except Exception as exc:
        logger.error("[billing] create_session failed: %s", exc)
        order.status = "failed"
        db.commit()
        raise HTTPException(status_code=502, detail=f"決済セッション作成に失敗しました: {exc}")

    order.provider_session_id = session.session_id
    db.commit()

    log_access(
        db, "billing_order_created",
        user_id=ctx.user_id,
        resource_type="billing_order",
        resource_id=order.id,
        ip_addr=_client_ip(request),
        details={
            "public_id": order.public_id,
            "product_code": product.code,
            "amount_jpy": order.amount_jpy,
            "provider": provider_name,
            "payment_method": body.payment_method,
        },
    )
    return {
        "success": True,
        "data": {
            "public_id": order.public_id,
            "redirect_url": session.redirect_url,
            "amount_jpy": order.amount_jpy,
            "payment_method": body.payment_method,
            "provider": provider_name,
        },
    }


@router.get("/orders/{public_id}")
def get_order(public_id: str = PathParam(..., min_length=10, max_length=80),
              request: Request = None, db: Session = Depends(get_db)):
    _require_billing_enabled()
    ctx = _require_login(request)
    o = db.query(BillingOrder).filter(BillingOrder.public_id == public_id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if not ctx.is_admin and o.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    return {"success": True, "data": _serialize_order(o, for_admin=ctx.is_admin)}


@router.post("/orders/{public_id}/cancel")
def cancel_order(public_id: str = PathParam(..., min_length=10, max_length=80),
                 request: Request = None, db: Session = Depends(get_db)):
    _require_billing_enabled()
    ctx = _require_login(request)
    o = db.query(BillingOrder).filter(BillingOrder.public_id == public_id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if not ctx.is_admin and o.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if o.status not in ("pending", "authorized"):
        raise HTTPException(status_code=409, detail=f"この状態の注文はキャンセルできません: {o.status}")
    o.status = "canceled"
    db.commit()
    log_access(
        db, "billing_order_canceled",
        user_id=ctx.user_id, resource_type="billing_order", resource_id=o.id,
        details={"public_id": public_id},
    )
    return {"success": True, "data": _serialize_order(o, for_admin=ctx.is_admin)}


# ─── 2. Webhook 受信 (no-auth, 署名検証) ─────────────────────────────────

async def _handle_webhook(provider_name: str, request: Request, db: Session) -> dict:
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    provider = get_provider_by_name(provider_name)

    verified = provider.verify_webhook(raw, headers)
    evt = provider.parse_webhook(raw, headers) if verified else None

    # 既知 event_id なら冪等扱い (二重処理防止)
    if evt is not None:
        existing = (
            db.query(BillingWebhookEvent)
            .filter(
                BillingWebhookEvent.provider == provider_name,
                BillingWebhookEvent.event_id == evt.event_id,
            )
            .first()
        )
        if existing is not None:
            return {"success": True, "data": {"duplicate": True, "event_id": evt.event_id}}

    rec = BillingWebhookEvent(
        provider=provider_name,
        event_id=(evt.event_id if evt else f"unverified_{_uuid.uuid4().hex}"),
        event_type=(evt.event_type if evt else "unverified"),
        raw_payload=raw.decode("utf-8", errors="replace")[:50_000],
        signature_verified=verified,
    )
    db.add(rec)
    db.flush()

    if not verified:
        rec.error = "signature verification failed"
        db.commit()
        log_access(db, "billing_webhook_invalid_signature",
                   details={"provider": provider_name})
        raise HTTPException(status_code=401, detail="invalid signature")

    if evt is None:
        rec.error = "parse failed"
        db.commit()
        return {"success": False, "data": {"reason": "parse failed"}}

    # 注文を更新
    order = None
    if evt.provider_session_id:
        order = (
            db.query(BillingOrder)
            .filter(BillingOrder.provider_session_id == evt.provider_session_id)
            .first()
        )
    if order is None and evt.provider_payment_id:
        order = (
            db.query(BillingOrder)
            .filter(BillingOrder.provider_payment_id == evt.provider_payment_id)
            .first()
        )
    if order is not None:
        rec.related_order_id = order.id
        if evt.event_type == "payment.succeeded":
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            if evt.provider_payment_id:
                order.provider_payment_id = evt.provider_payment_id
        elif evt.event_type == "payment.authorized":
            order.status = "authorized"
        elif evt.event_type == "payment.failed":
            order.status = "failed"
        elif evt.event_type == "payment.canceled":
            order.status = "canceled"
        elif evt.event_type == "session.expired":
            if order.status == "pending":
                order.status = "expired"
        elif evt.event_type == "refund.created":
            order.status = "refunded"
            order.refunded_at = datetime.utcnow()

    rec.processed_at = datetime.utcnow()
    db.commit()

    log_access(
        db, f"billing_webhook_{evt.event_type.replace('.', '_')}",
        resource_type="billing_order",
        resource_id=order.id if order else None,
        details={
            "provider": provider_name,
            "event_id": evt.event_id,
            "amount_jpy": evt.amount_jpy,
        },
    )
    return {"success": True, "data": {"event_id": evt.event_id, "type": evt.event_type}}


@router.post("/webhooks/stripe")
async def webhook_stripe(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("stripe", request, db)


@router.post("/webhooks/komoju")
async def webhook_komoju(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("komoju", request, db)


@router.post("/webhooks/univapay")
async def webhook_univapay(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook("univapay", request, db)


# ─── 3. 権利 (entitlements) ─────────────────────────────────────────────

@router.get("/entitlements")
def list_my_entitlements(request: Request, db: Session = Depends(get_db)):
    _require_billing_enabled()
    ctx = _require_login(request)
    rows = (
        db.query(BillingEntitlement)
        .filter(
            BillingEntitlement.user_id == ctx.user_id,
            BillingEntitlement.revoked_at.is_(None),
        )
        .order_by(BillingEntitlement.created_at.desc())
        .all()
    )
    return {
        "success": True,
        "data": [
            {
                "entitlement_type": r.entitlement_type,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            }
            for r in rows
        ],
    }


# ─── 4. admin ─────────────────────────────────────────────────────────

@router.get("/admin/orders")
def admin_list_orders(request: Request, db: Session = Depends(get_db),
                      limit: int = 100, status: Optional[str] = None):
    _require_billing_enabled()
    _require_admin(request)
    if limit > 1000:
        limit = 1000
    q = db.query(BillingOrder)
    if status:
        q = q.filter(BillingOrder.status == status)
    rows = q.order_by(BillingOrder.id.desc()).limit(limit).all()
    return {
        "success": True,
        "data": [_serialize_order(o, for_admin=True) for o in rows],
        "meta": {"count": len(rows), "limit": limit},
    }


@router.get("/admin/products")
def admin_list_products(request: Request, db: Session = Depends(get_db)):
    _require_billing_enabled()
    _require_admin(request)
    rows = db.query(BillingProduct).order_by(BillingProduct.id.desc()).all()
    return {
        "success": True,
        "data": [
            {
                "id": p.id, "code": p.code, "name": p.name,
                "description": p.description, "price_jpy": p.price_jpy,
                "is_active": p.is_active,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in rows
        ],
    }


@router.post("/admin/products", status_code=201)
def admin_create_product(body: CreateProductRequest, request: Request,
                         db: Session = Depends(get_db)):
    _require_billing_enabled()
    ctx = _require_admin(request)
    existing = db.query(BillingProduct).filter(BillingProduct.code == body.code).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"product code 既存: {body.code}")
    p = BillingProduct(
        code=body.code, name=body.name, description=body.description,
        price_jpy=body.price_jpy, is_active=body.is_active,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    log_access(db, "billing_product_created",
               user_id=ctx.user_id, resource_type="billing_product", resource_id=p.id,
               details={"code": body.code, "price_jpy": body.price_jpy})
    return {"success": True, "data": {"id": p.id, "code": p.code}}


@router.post("/admin/refund/{order_id}")
def admin_refund(order_id: int, request: Request, db: Session = Depends(get_db),
                 amount_jpy: Optional[int] = None):
    _require_billing_enabled()
    ctx = _require_admin(request)
    o = db.get(BillingOrder, order_id)
    if o is None:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if o.status != "paid" or not o.provider_payment_id:
        raise HTTPException(status_code=409, detail=f"返金可能な注文ではありません (status={o.status})")
    if amount_jpy is not None and (amount_jpy < 1 or amount_jpy > o.amount_jpy):
        raise HTTPException(status_code=422, detail="返金金額が不正です")
    provider = get_provider_by_name(o.provider or "noop")
    try:
        result = provider.refund(o.provider_payment_id, amount_jpy)
    except Exception as exc:
        logger.error("[billing] refund failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"返金処理に失敗: {exc}")
    o.status = "refunded"
    o.refunded_at = datetime.utcnow()
    db.commit()
    log_access(db, "billing_refunded", user_id=ctx.user_id,
               resource_type="billing_order", resource_id=o.id,
               details={"refund_id": result.refund_id, "amount_jpy": result.amount_jpy})
    return {
        "success": True,
        "data": {
            "refund_id": result.refund_id,
            "amount_jpy": result.amount_jpy,
            "status": result.status,
        },
    }


@router.get("/orders/{public_id}/receipt")
def download_receipt(public_id: str = PathParam(..., min_length=10, max_length=80),
                     request: Request = None, db: Session = Depends(get_db)):
    """注文の領収書 PDF をダウンロードする (本人 / admin、status=paid のみ)。

    インボイス番号 (env: SS_INVOICE_REGISTRATION_NUMBER) が設定されていれば
    自動的に「適格請求書 兼 領収書」として発行される。
    """
    _require_billing_enabled()
    ctx = _require_login(request)
    o = db.query(BillingOrder).filter(BillingOrder.public_id == public_id).first()
    if o is None:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if not ctx.is_admin and o.user_id != ctx.user_id:
        raise HTTPException(status_code=404, detail="注文が見つかりません")
    if o.status != "paid":
        raise HTTPException(status_code=409, detail=f"領収書発行可能な状態ではありません (status={o.status})")

    # 顧客宛名: display_name または email
    target_user = db.get(User, o.user_id)
    customer = ""
    if target_user is not None:
        customer = (target_user.display_name or target_user.username or
                    getattr(target_user, "email", None) or f"user_{o.user_id}")

    # 商品名
    product = db.get(BillingProduct, o.product_id)
    product_name = product.name if product else "商品"

    # 決済手段ラベル
    PM_LABELS = {
        "credit_card": "クレジットカード",
        "apple_pay": "Apple Pay", "google_pay": "Google Pay",
        "paypay": "PayPay", "merpay": "メルペイ",
        "rakuten_pay": "楽天ペイ", "linepay": "LINE Pay",
        "konbini": "コンビニ決済", "bank_transfer": "銀行振込",
        "d_barai": "d 払い", "au_pay": "au PAY",
    }
    pm_label = PM_LABELS.get(o.payment_method or "", o.payment_method or "")

    from backend.services.billing.receipt import generate_receipt_pdf
    try:
        pdf_bytes = generate_receipt_pdf(
            order_public_id=o.public_id,
            issued_at=datetime.utcnow(),
            customer_display=customer,
            product_name=product_name,
            amount_jpy=o.amount_jpy,
            payment_method_label=pm_label,
            paid_at=o.paid_at,
        )
    except Exception as exc:
        logger.error("[billing] receipt PDF gen failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"領収書生成に失敗: {exc}")

    log_access(db, "billing_receipt_downloaded",
               user_id=ctx.user_id, resource_type="billing_order", resource_id=o.id,
               details={"public_id": public_id})

    from fastapi import Response
    filename = f"receipt_{o.public_id[:12]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/grant_entitlement", status_code=201)
def admin_grant_entitlement(body: GrantEntitlementRequest, request: Request,
                            db: Session = Depends(get_db)):
    """admin が手動で権利付与する (無償提供 / 補填用)。"""
    _require_billing_enabled()
    ctx = _require_admin(request)
    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    valid_to = None
    if body.valid_to_iso:
        try:
            valid_to = datetime.fromisoformat(body.valid_to_iso)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="valid_to_iso の形式が不正です")
    ent = BillingEntitlement(
        user_id=body.user_id,
        entitlement_type=body.entitlement_type,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        valid_to=valid_to,
        granted_by_user_id=ctx.user_id,
        note=body.note,
    )
    db.add(ent)
    db.commit()
    log_access(db, "billing_admin_grant",
               user_id=ctx.user_id, resource_type="billing_entitlement", resource_id=ent.id,
               details={
                   "target_user_id": body.user_id,
                   "type": body.entitlement_type,
                   "resource_type": body.resource_type,
                   "resource_id": body.resource_id,
               })
    return {"success": True, "data": {"id": ent.id}}
