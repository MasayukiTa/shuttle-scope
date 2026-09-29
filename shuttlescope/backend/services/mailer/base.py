"""Mailer 共通インターフェース。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MailMessage:
    """送信するメール 1 通の表現。"""
    to: List[str]                       # 宛先 (複数可)
    subject: str                        # 件名 (UTF-8)
    text_body: str                      # プレーンテキスト本文
    html_body: Optional[str] = None     # HTML 本文 (オプション)
    reply_to: Optional[str] = None      # Reply-To
    tags: List[str] = field(default_factory=list)  # ログ用タグ (mail_type 等)


class Mailer(ABC):
    """全 mailer 実装が満たすインターフェース。"""

    @abstractmethod
    def send(self, msg: MailMessage) -> bool:
        """メールを送信する。成功したら True、失敗したら False。

        失敗時は例外を投げず False を返すこと（呼び出し側の業務ロジックを
        止めないため）。具体的なエラーは内部でログに記録する。
        """
        raise NotImplementedError

    def from_address(self) -> str:
        """送信元アドレスを返す。SS_MAIL_FROM 設定値 または fallback。"""
        try:
            from backend.config import settings
            return (getattr(settings, "ss_mail_from", "") or "no-reply@shuttle-scope.com").strip()
        except Exception:
            import os
            return (os.environ.get("SS_MAIL_FROM", "") or "no-reply@shuttle-scope.com").strip()

    def from_name(self) -> str:
        try:
            from backend.config import settings
            return (getattr(settings, "ss_mail_from_name", "") or "ShuttleScope").strip()
        except Exception:
            import os
            return (os.environ.get("SS_MAIL_FROM_NAME", "") or "ShuttleScope").strip()
