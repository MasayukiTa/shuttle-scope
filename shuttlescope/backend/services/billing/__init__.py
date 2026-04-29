"""Phase Pay-1: 課金 / 決済プロバイダ抽象化レイヤ。

3 プロバイダ並列構成:
  - Stripe   : カード / Apple Pay / Google Pay / 国際カード
  - KOMOJU   : PayPay / メルペイ / 楽天ペイ / LINE Pay / コンビニ / 銀行振込
  - Univapay : d 払い / au PAY (Phase Pay-3 で本実装、現状 stub)

PaymentRouter:
  payment_method 文字列 (例: "paypay", "credit_card") を受け取り、
  対応する PaymentProvider インスタンスを返す。

セキュリティ:
  - フロント完全非公開、API レスポンスにも payment 情報は出さない
  - SS_BILLING_ENABLED=0 の間は API 全 503
  - OpenAPI / Swagger からも include_in_schema=False で隠蔽
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import PaymentProvider, PaymentSession, RefundResult, WebhookEvent  # noqa: F401

logger = logging.getLogger(__name__)


# 決済手段 → プロバイダ名のルーティング表
PAYMENT_METHOD_ROUTING: dict[str, str] = {
    # Stripe
    "credit_card":   "stripe",
    "apple_pay":     "stripe",
    "google_pay":    "stripe",
    # KOMOJU
    "paypay":        "komoju",
    "merpay":        "komoju",
    "rakuten_pay":   "komoju",
    "linepay":       "komoju",
    "konbini":       "komoju",
    "bank_transfer": "komoju",
    # Univapay (Phase Pay-3)
    "d_barai":       "univapay",
    "au_pay":        "univapay",
}

# サポートする全決済手段 (UI 表示用)
SUPPORTED_PAYMENT_METHODS = list(PAYMENT_METHOD_ROUTING.keys())


def is_billing_enabled() -> bool:
    """SS_BILLING_ENABLED が 1 のときのみ True。デフォルト無効 (503)。"""
    try:
        from backend.config import settings
        return bool(int(getattr(settings, "ss_billing_enabled", 0) or 0))
    except Exception:
        return os.environ.get("SS_BILLING_ENABLED", "0") == "1"


def get_provider_for_method(method: str) -> PaymentProvider:
    """決済手段に対応する PaymentProvider を返す。"""
    name = PAYMENT_METHOD_ROUTING.get(method)
    if name is None:
        raise ValueError(f"未対応の決済手段: {method}")
    return get_provider_by_name(name)


def get_provider_by_name(name: str) -> PaymentProvider:
    """プロバイダ名で直接取得 (Webhook 経路で使用)。"""
    if name == "stripe":
        from .stripe_provider import StripeProvider
        return StripeProvider()
    if name == "komoju":
        from .komoju_provider import KomojuProvider
        return KomojuProvider()
    if name == "univapay":
        from .univapay_provider import UnivapayProvider
        return UnivapayProvider()
    if name == "noop":
        from .noop import NoopProvider
        return NoopProvider()
    raise ValueError(f"未知のプロバイダ: {name}")
