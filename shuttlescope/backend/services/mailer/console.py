"""ConsoleMailer: 開発・CI 用にメールをログに出すだけ。"""
from __future__ import annotations

import logging

from .base import Mailer, MailMessage

logger = logging.getLogger(__name__)


class ConsoleMailer(Mailer):
    """メールを実際には送らず INFO ログに出力する。

    開発環境で「メール内容を確認したい」場合に有用。
    本番では絶対に使わないこと（実送信されないため）。
    """

    def send(self, msg: MailMessage) -> bool:
        sender = f"{self.from_name()} <{self.from_address()}>"
        logger.info(
            "[mailer:console] ===== email simulated =====\n"
            "  From: %s\n  To: %s\n  Subject: %s\n  Tags: %s\n"
            "  --- text body ---\n%s\n  --- end ---",
            sender, ", ".join(msg.to), msg.subject, msg.tags, msg.text_body,
        )
        if msg.html_body:
            logger.debug("[mailer:console] HTML body length=%d", len(msg.html_body))
        return True
