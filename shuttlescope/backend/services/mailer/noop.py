"""NoopMailer: テスト用。何もしないが送信ログは保持する。"""
from __future__ import annotations

import logging
from typing import List

from .base import Mailer, MailMessage

logger = logging.getLogger(__name__)


class NoopMailer(Mailer):
    """送信履歴を in-memory に蓄積する。テストアサーションで参照可能。"""

    def __init__(self):
        self.sent: List[MailMessage] = []

    def send(self, msg: MailMessage) -> bool:
        self.sent.append(msg)
        logger.debug("[mailer:noop] queued: to=%s subject=%s", msg.to, msg.subject)
        return True

    def clear(self) -> None:
        self.sent.clear()
