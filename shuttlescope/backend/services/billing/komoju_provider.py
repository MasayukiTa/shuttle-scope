"""KOMOJU プロバイダ実装 (PayPay / メルペイ / 楽天ペイ / LINE Pay / コンビニ / 銀行振込)。

API: https://docs.komoju.com/en/api/
Webhook: HMAC-SHA256 (X-Komoju-Signature ヘッダ)

KOMOJU の payment_method 文字列:
  - paypay / merpay / rakuten_pay / linepay / konbini / bank_transfer
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import json
import logging
import urllib.request
from typing import Optional

from .base import PaymentProvider, PaymentSession, RefundResult, WebhookEvent

logger = logging.getLogger(__name__)


# フロントの payment_method → KOMOJU の payment_method 名
_KOMOJU_PM_MAP = {
    "paypay":        "paypay",
    "merpay":        "merpay",
    "rakuten_pay":   "rakuten_pay",
    "linepay":       "linepay",
    "konbini":       "konbini",
    "bank_transfer": "bank_transfer",
}


class KomojuProvider(PaymentProvider):
    name = "komoju"

    def _api_base(self) -> str:
        v = self._get_setting("ss_komoju_api_base", "SS_KOMOJU_API_BASE")
        return v or "https://komoju.com/api/v1"

    def _secret_key(self) -> str:
        return self._get_setting("ss_komoju_secret_key", "SS_KOMOJU_SECRET_KEY")

    def _webhook_secret(self) -> str:
        return self._get_setting("ss_komoju_webhook_secret", "SS_KOMOJU_WEBHOOK_SECRET")

    def _api_request(self, path: str, payload: dict, method: str = "POST") -> dict:
        sk = self._secret_key()
        if not sk:
            raise RuntimeError("SS_KOMOJU_SECRET_KEY 未設定")
        body = json.dumps(payload).encode("utf-8") if payload else None
        # KOMOJU は HTTP Basic 認証 (secret_key を user に、password 空)
        basic = base64.b64encode(f"{sk}:".encode("utf-8")).decode("ascii")
        req = urllib.request.Request(
            f"{self._api_base()}{path}",
            data=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        # nosec B310: URL built from hardcoded https Komoju API base.
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    def create_session(
        self, *, order_public_id, amount_jpy, product_name,
        payment_method, return_url, cancel_url, customer_email=None,
    ) -> PaymentSession:
        komoju_pm = _KOMOJU_PM_MAP.get(payment_method)
        if komoju_pm is None:
            raise ValueError(f"KOMOJU 未対応の決済手段: {payment_method}")
        # KOMOJU Hosted Sessions: https://docs.komoju.com/en/api/resources/sessions/
        payload = {
            "amount": amount_jpy,
            "currency": "JPY",
            "default_locale": "ja",
            "payment_types": [komoju_pm],
            "return_url": f"{return_url}?order_id={order_public_id}",
            "cancel_url": f"{cancel_url}?order_id={order_public_id}",
            "metadata": {
                "order_public_id": order_public_id,
                "product_name": product_name,
            },
        }
        if customer_email:
            payload["customer"] = {"email": customer_email}
        result = self._api_request("/sessions", payload, method="POST")
        return PaymentSession(
            session_id=result["id"],
            redirect_url=result["session_url"],
            expires_at_iso=result.get("expires_at"),
            extra={"raw": result},
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        secret = self._webhook_secret()
        if not secret:
            logger.warning("[komoju] webhook secret 未設定")
            return False
        sig = (headers.get("x-komoju-signature") or headers.get("X-Komoju-Signature") or "").strip()
        if not sig:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def parse_webhook(self, raw_body: bytes, headers: dict) -> Optional[WebhookEvent]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            logger.error("[komoju] webhook json parse failed: %s", exc)
            return None
        evt_id = payload.get("id", "")
        evt_type_raw = payload.get("type", "")
        TYPE_MAP = {
            "payment.captured":  "payment.succeeded",
            "payment.authorized":"payment.authorized",
            "payment.failed":    "payment.failed",
            "payment.cancelled": "payment.canceled",
            "payment.expired":   "session.expired",
            "payment.refunded":  "refund.created",
        }
        evt_type = TYPE_MAP.get(evt_type_raw, evt_type_raw)
        data = payload.get("data") or {}
        meta = (data.get("metadata") or {}) if isinstance(data, dict) else {}
        return WebhookEvent(
            event_id=evt_id,
            event_type=evt_type,
            provider="komoju",
            provider_payment_id=data.get("id"),
            provider_session_id=data.get("session"),
            amount_jpy=data.get("amount"),
            payment_method=data.get("payment_method", {}).get("type") if isinstance(data.get("payment_method"), dict) else None,
            raw=payload,
        )

    def refund(self, payment_id: str, amount_jpy: Optional[int] = None) -> RefundResult:
        payload: dict = {}
        if amount_jpy is not None:
            payload["amount"] = amount_jpy
        result = self._api_request(f"/payments/{payment_id}/refund", payload, method="POST")
        return RefundResult(
            refund_id=result.get("id", ""),
            amount_jpy=int(result.get("amount", 0)),
            status="succeeded" if result.get("status") == "refunded" else str(result.get("status", "unknown")),
            raw=result,
        )
