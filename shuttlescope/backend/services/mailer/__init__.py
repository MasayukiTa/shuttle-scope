"""Mailer 抽象化レイヤ (M-A1)。

3 バックエンド:
  - console: dev / CI 用 (ログに出すだけ)
  - mailchannels_worker: 本番 (Cloudflare Worker 経由 MailChannels)
  - noop: テスト用 (何もしない)

設定:
  SS_MAIL_BACKEND=console | mailchannels_worker | noop  (デフォルト: console)
  SS_MAIL_FROM=no-reply@shuttle-scope.com
  SS_MAIL_FROM_NAME=ShuttleScope
  SS_MAILCHANNELS_WORKER_URL=https://mail.example.workers.dev  (本番のみ)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .base import Mailer, MailMessage  # noqa: F401

logger = logging.getLogger(__name__)

_mailer_singleton: Optional[Mailer] = None


def get_mailer() -> Mailer:
    """設定に応じた Mailer インスタンスを返す（シングルトン）。"""
    global _mailer_singleton
    if _mailer_singleton is not None:
        return _mailer_singleton

    try:
        from backend.config import settings
        backend = (getattr(settings, "ss_mail_backend", "") or "").strip().lower()
    except Exception:
        backend = (os.environ.get("SS_MAIL_BACKEND", "") or "").strip().lower()

    if not backend:
        backend = "console"  # デフォルト

    if backend == "noop":
        from .noop import NoopMailer
        _mailer_singleton = NoopMailer()
    elif backend == "mailchannels_worker":
        from .mailchannels import MailChannelsWorkerMailer
        _mailer_singleton = MailChannelsWorkerMailer()
    else:
        from .console import ConsoleMailer
        _mailer_singleton = ConsoleMailer()

    logger.info("[mailer] backend selected: %s -> %s",
                backend, type(_mailer_singleton).__name__)
    return _mailer_singleton


def reset_mailer_for_test() -> None:
    """テスト用: シングルトンをリセットする。"""
    global _mailer_singleton
    _mailer_singleton = None
