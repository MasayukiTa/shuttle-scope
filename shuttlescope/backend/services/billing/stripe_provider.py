"""Stripe プロバイダ実装 (カード / Apple Pay / Google Pay / 国際カード)。

設計方針:
  - Stripe Checkout (ホスト型) を使用 → カード情報は自サーバ通過しない (PCI SAQ A)
  - SDK は使わず標準 urllib のみ (依存追加しない、stripe-python なしで動く)
  - Webhook は Stripe-Signature ヘッダで HMAC-SHA256 検証

API:
  https://stripe.com/docs/api/checkout/sessions/create
  https://stripe.com/docs/api/refunds/create
  https://stripe.com/docs/webhooks/signatures
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Optional

from .base import PaymentProvider, PaymentSession, RefundResult, WebhookEvent

logger = logging.getLogger(__name__)

_STRIPE_API_BASE = "https://api.stripe.com/v1"
_TOLERANCE_SECONDS = 5 * 60  # 5 分以上古い Webhook は拒否


# Stripe payment_method_types とフロントの payment_method の対応
_STRIPE_PM_MAP = {
    "credit_card": ["card"],
    "apple_pay":   ["card"],   # Stripe では card 内で wallet 自動判定
    "google_pay":  ["card"],
}


class StripeProvider(PaymentProvider):
    name = "stripe"

    def _secret_key(self) -> str:
        return self._get_setting("ss_stripe_secret_key", "SS_STRIPE_SECRET_KEY")

    def _webhook_secret(self) -> str:
        return self._get_setting("ss_stripe_webhook_secret", "SS_STRIPE_WEBHOOK_SECRET")

    def _api_request(self, path: str, params: dict, method: str = "POST") -> dict:
        sk = self._secret_key()
        if not sk:
            raise RuntimeError("SS_STRIPE_SECRET_KEY 未設定")
        body = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
        req = urllib.request.Request(
            f"{_STRIPE_API_BASE}{path}",
            data=body if method == "POST" else None,
            headers={
                "Authorization": f"Bearer {sk}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Stripe-Version": "2024-11-20.acacia",
            },
            method=method,
        )
        # nosec B310: URL is built from a hardcoded https constant (_STRIPE_API_BASE).
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def create_session(
        self, *, order_public_id, amount_jpy, product_name,
        payment_method, return_url, cancel_url, customer_email=None,
    ) -> PaymentSession:
        pm_types = _STRIPE_PM_MAP.get(payment_method, ["card"])
        params: dict = {
            "mode": "payment",
            "currency": "jpy",
            "line_items[0][price_data][currency]": "jpy",
            "line_items[0][price_data][unit_amount]": str(amount_jpy),
            "line_items[0][price_data][product_data][name]": product_name,
            "line_items[0][quantity]": "1",
            "success_url": return_url + "?order_id=" + order_public_id,
            "cancel_url": cancel_url + "?order_id=" + order_public_id,
            "client_reference_id": order_public_id,
            "metadata[order_public_id]": order_public_id,
        }
        for i, t in enumerate(pm_types):
            params[f"payment_method_types[{i}]"] = t
        if customer_email:
            params["customer_email"] = customer_email
        result = self._api_request("/checkout/sessions", params, method="POST")
        return PaymentSession(
            session_id=result["id"],
            redirect_url=result["url"],
            expires_at_iso=str(result.get("expires_at")),
            extra={"raw": result},
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        secret = self._webhook_secret()
        if not secret:
            logger.warning("[stripe] webhook secret 未設定")
            return False
        sig_header = headers.get("stripe-signature") or headers.get("Stripe-Signature") or ""
        if not sig_header:
            return False
        # Stripe-Signature: t=TIMESTAMP,v1=SIGNATURE,v1=...
        parts = {}
        for chunk in sig_header.split(","):
            if "=" not in chunk:
                continue
            k, v = chunk.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
        try:
            ts = int(parts.get("t", ["0"])[0])
        except ValueError:
            return False
        if abs(int(time.time()) - ts) > _TOLERANCE_SECONDS:
            logger.warning("[stripe] webhook timestamp out of tolerance: %d", ts)
            return False
        signed_payload = f"{ts}.".encode("utf-8") + raw_body
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        for sig in parts.get("v1", []):
            if hmac.compare_digest(expected, sig):
                return True
        return False

    def parse_webhook(self, raw_body: bytes, headers: dict) -> Optional[WebhookEvent]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            logger.error("[stripe] webhook json parse failed: %s", exc)
            return None
        evt_id = payload.get("id", "")
        evt_type_raw = payload.get("type", "")
        # 正規化マッピング
        TYPE_MAP = {
            "checkout.session.completed":   "payment.succeeded",
            "checkout.session.expired":     "session.expired",
            "payment_intent.succeeded":     "payment.succeeded",
            "payment_intent.payment_failed":"payment.failed",
            "charge.refunded":              "refund.created",
        }
        evt_type = TYPE_MAP.get(evt_type_raw, evt_type_raw)
        data = (payload.get("data") or {}).get("object") or {}
        return WebhookEvent(
            event_id=evt_id,
            event_type=evt_type,
            provider="stripe",
            provider_session_id=data.get("id") if data.get("object") == "checkout.session" else data.get("payment_intent"),
            provider_payment_id=data.get("payment_intent") or data.get("id"),
            amount_jpy=data.get("amount_total") or data.get("amount"),
            payment_method=(data.get("payment_method_types") or [None])[0] if isinstance(data.get("payment_method_types"), list) else None,
            raw=payload,
        )

    def refund(self, payment_id: str, amount_jpy: Optional[int] = None) -> RefundResult:
        params = {"payment_intent": payment_id}
        if amount_jpy is not None:
            params["amount"] = str(amount_jpy)
        result = self._api_request("/refunds", params, method="POST")
        return RefundResult(
            refund_id=result["id"],
            amount_jpy=int(result.get("amount", 0)),
            status=str(result.get("status", "unknown")),
            raw=result,
        )
