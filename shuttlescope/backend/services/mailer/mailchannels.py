"""MailChannelsWorkerMailer: Cloudflare Worker 経由で MailChannels に送信する。

設定:
  SS_MAILCHANNELS_WORKER_URL — Worker のエンドポイント URL
  Worker は HTTPS POST で MailMessage を受け取り、内部で MailChannels API を叩く。

Worker 側のリファレンス実装は private_docs/cloudflare_mail_flow_guide.md に記載。

セキュリティ:
  Worker URL は機密。漏洩しても認証なしでメール送信可能になるため、
  Worker 側で X-Auth-Token ヘッダ認証を必ず実装すること。
  本クライアントは SS_MAILCHANNELS_WORKER_AUTH_TOKEN を Authorization: Bearer で送る。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional

from .base import Mailer, MailMessage

logger = logging.getLogger(__name__)


class MailChannelsWorkerMailer(Mailer):
    def _worker_url(self) -> Optional[str]:
        try:
            from backend.config import settings
            v = (getattr(settings, "ss_mailchannels_worker_url", "") or "").strip()
        except Exception:
            v = (os.environ.get("SS_MAILCHANNELS_WORKER_URL", "") or "").strip()
        return v or None

    def _worker_auth(self) -> Optional[str]:
        try:
            from backend.config import settings
            v = (getattr(settings, "ss_mailchannels_worker_auth_token", "") or "").strip()
        except Exception:
            v = (os.environ.get("SS_MAILCHANNELS_WORKER_AUTH_TOKEN", "") or "").strip()
        return v or None

    def send(self, msg: MailMessage) -> bool:
        url = self._worker_url()
        if not url:
            logger.error("[mailer:mailchannels] SS_MAILCHANNELS_WORKER_URL 未設定")
            return False

        payload = {
            "personalizations": [{"to": [{"email": addr} for addr in msg.to]}],
            "from": {"email": self.from_address(), "name": self.from_name()},
            "subject": msg.subject,
            "content": [
                {"type": "text/plain", "value": msg.text_body},
            ],
        }
        if msg.html_body:
            payload["content"].append({"type": "text/html", "value": msg.html_body})
        if msg.reply_to:
            payload["reply_to"] = {"email": msg.reply_to}

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        auth = self._worker_auth()
        if auth:
            headers["Authorization"] = f"Bearer {auth}"

        if not url.startswith("https://"):
            logger.error("[mailer:mailchannels] SS_MAILCHANNELS_WORKER_URL must be https://")
            return False
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            # scheme guarded above; URL is operator-supplied Cloudflare Worker.
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310
                if 200 <= resp.status < 300:
                    logger.info("[mailer:mailchannels] sent: to=%s subject=%s status=%d",
                                msg.to, msg.subject, resp.status)
                    return True
                logger.error("[mailer:mailchannels] worker returned %d: %s",
                             resp.status, resp.read()[:200])
                return False
        except Exception as exc:
            logger.error("[mailer:mailchannels] send failed: %s", exc)
            return False
