"""Univapay プロバイダ実装 stub (d 払い / au PAY)。

Phase Pay-3 で本実装。現状は構造のみ提供し、実際に呼ばれると NotImplementedError。

API: https://docs.univapay.com/api/

実装時の注意:
  - Univapay は OAuth2 + App Token 認証
  - Webhook は X-Univapay-Signature (HMAC-SHA256)
  - d 払い / au PAY はセッションリダイレクト方式
"""
from __future__ import annotations

import logging
from typing import Optional

from .base import PaymentProvider, PaymentSession, RefundResult, WebhookEvent

logger = logging.getLogger(__name__)


class UnivapayProvider(PaymentProvider):
    """Phase Pay-3 で本実装予定の Univapay スタブ。"""

    name = "univapay"

    def _app_token(self) -> str:
        return self._get_setting("ss_univapay_app_token", "SS_UNIVAPAY_APP_TOKEN")

    def _app_secret(self) -> str:
        return self._get_setting("ss_univapay_app_secret", "SS_UNIVAPAY_APP_SECRET")

    def _webhook_secret(self) -> str:
        return self._get_setting("ss_univapay_webhook_secret", "SS_UNIVAPAY_WEBHOOK_SECRET")

    def create_session(self, **kwargs) -> PaymentSession:
        if not self._app_token():
            raise NotImplementedError(
                "Univapay は Phase Pay-3 で実装予定。SS_UNIVAPAY_APP_TOKEN 未設定。"
            )
        # TODO Phase Pay-3: Univapay /charges API
        raise NotImplementedError("Univapay createSession は Phase Pay-3 で実装")

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        # TODO Phase Pay-3: HMAC-SHA256 検証
        logger.warning("[univapay] verify_webhook is stub (Phase Pay-3)")
        return False

    def parse_webhook(self, raw_body: bytes, headers: dict) -> Optional[WebhookEvent]:
        logger.warning("[univapay] parse_webhook is stub (Phase Pay-3)")
        return None

    def refund(self, payment_id: str, amount_jpy: Optional[int] = None) -> RefundResult:
        raise NotImplementedError("Univapay refund は Phase Pay-3 で実装")
