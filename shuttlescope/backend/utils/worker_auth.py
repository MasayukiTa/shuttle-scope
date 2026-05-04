"""R-3: Worker 認証ユーティリティ (HTTP 配信のみの予備実装)。

Worker PC が現地に持ち込めない可能性が高いため、これは予備機能。
主用途: クラウド/オフサイトの Worker (Ray / 別 PC 等) が録画ファイルを取得する。

設定:
  SS_WORKER_AUTH_TOKEN      共有秘密 (32 文字以上推奨)。空 = Worker 機能無効

セキュリティ:
  - HMAC 比較で timing attack を防ぐ
  - Worker トークンは管理者のみが知るため、漏洩したら env 変更で即無効化
  - SS_WORKER_AUTH_TOKEN が空の間は全 Worker API が 503 を返す
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _expected_token() -> str:
    try:
        from backend.config import settings
        return (getattr(settings, "ss_worker_auth_token", "") or "").strip()
    except Exception:
        return (os.environ.get("SS_WORKER_AUTH_TOKEN", "") or "").strip()


def is_worker_enabled() -> bool:
    """SS_WORKER_AUTH_TOKEN が設定されていれば Worker 機能 ON。"""
    return bool(_expected_token())


def verify_worker_token(token: Optional[str]) -> bool:
    """Worker トークンを timing-safe に検証。"""
    expected = _expected_token()
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, token)
