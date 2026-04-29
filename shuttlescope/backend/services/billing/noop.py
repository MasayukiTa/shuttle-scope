"""NoopProvider: テスト用。実 API を呼ばず、in-memory に履歴を保持する。"""
from __future__ import annotations

from typing import List, Optional

from .base import PaymentProvider, PaymentSession, RefundResult, WebhookEvent


class NoopProvider(PaymentProvider):
    name = "noop"

    def __init__(self):
        self.sessions: List[dict] = []
        self.refunds: List[dict] = []

    def create_session(self, **kwargs) -> PaymentSession:
        self.sessions.append(kwargs)
        return PaymentSession(
            session_id=f"noop_session_{len(self.sessions)}",
            redirect_url=f"https://noop.example.com/checkout/{len(self.sessions)}",
        )

    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        return True

    def parse_webhook(self, raw_body: bytes, headers: dict) -> Optional[WebhookEvent]:
        return WebhookEvent(
            event_id=f"noop_evt_{hash(raw_body) & 0xffffffff}",
            event_type="payment.succeeded",
            provider="noop",
        )

    def refund(self, payment_id: str, amount_jpy: Optional[int] = None) -> RefundResult:
        self.refunds.append({"payment_id": payment_id, "amount": amount_jpy})
        return RefundResult(
            refund_id=f"noop_refund_{len(self.refunds)}",
            amount_jpy=amount_jpy or 0,
            status="succeeded",
        )
