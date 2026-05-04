"""PaymentProvider 抽象 IF。"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PaymentSession:
    """プロバイダの決済セッション (ホスト型 Checkout)。"""
    session_id: str            # プロバイダ側のセッション ID
    redirect_url: str          # ユーザーをリダイレクトする URL
    expires_at_iso: Optional[str] = None
    extra: dict = field(default_factory=dict)


@dataclass
class RefundResult:
    refund_id: str
    amount_jpy: int
    status: str                # "succeeded" / "pending" / "failed"
    raw: dict = field(default_factory=dict)


@dataclass
class WebhookEvent:
    """正規化された Webhook イベント。各プロバイダ固有の payload を共通形式に変換。"""
    event_id: str              # プロバイダ側の event ID (UNIQUE)
    event_type: str            # 正規化済: "payment.succeeded" / "payment.failed" / "refund.created" / "session.expired"
    provider: str              # "stripe" / "komoju" / "univapay"
    provider_payment_id: Optional[str] = None
    provider_session_id: Optional[str] = None
    amount_jpy: Optional[int] = None
    payment_method: Optional[str] = None
    raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    """全プロバイダ共通インターフェース。"""

    name: str = "abstract"

    @abstractmethod
    def create_session(
        self,
        *,
        order_public_id: str,
        amount_jpy: int,
        product_name: str,
        payment_method: str,
        return_url: str,
        cancel_url: str,
        customer_email: Optional[str] = None,
    ) -> PaymentSession:
        """ホスト型決済セッションを作成し、リダイレクト URL を返す。"""
        raise NotImplementedError

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict) -> bool:
        """Webhook 署名を検証する。失敗時は False。"""
        raise NotImplementedError

    @abstractmethod
    def parse_webhook(self, raw_body: bytes, headers: dict) -> Optional[WebhookEvent]:
        """検証済み Webhook を正規化された WebhookEvent に変換する。"""
        raise NotImplementedError

    @abstractmethod
    def refund(self, payment_id: str, amount_jpy: Optional[int] = None) -> RefundResult:
        """払い戻しを実行する。amount=None なら全額返金。"""
        raise NotImplementedError

    # ── 共通ユーティリティ ──────────────────────────────────────────────

    def _get_setting(self, key: str, fallback_env: str = "") -> str:
        try:
            from backend.config import settings
            return (getattr(settings, key, "") or "").strip()
        except Exception:
            return (os.environ.get(fallback_env or key.upper(), "") or "").strip()
