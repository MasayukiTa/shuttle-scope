"""Cloudflare Turnstile サーバー側検証。

Turnstile はクライアントが解いた結果トークンをサーバーに送り、
サーバーが Cloudflare の siteverify エンドポイントで検証する。

設定:
  SS_TURNSTILE_SECRET_KEY — Cloudflare ダッシュボードで取得した secret
  SS_TURNSTILE_SITE_KEY   — フロントが参照する公開キー (本ファイルでは未使用)
  SS_TURNSTILE_REQUIRED   — "1" で必須化、"0" で skip 可能 (デフォルト 0)

dev / 未設定時:
  SECRET_KEY が空なら常に True を返す (警告ログ)。
  これは dev 環境で Turnstile 統合をテストせずに progress するため。
  本番では必ず SS_TURNSTILE_REQUIRED=1 + SECRET_KEY 設定すること。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_warned_no_secret = False


def _secret() -> str:
    try:
        from backend.config import settings
        return (getattr(settings, "ss_turnstile_secret_key", "") or "").strip()
    except Exception:
        return (os.environ.get("SS_TURNSTILE_SECRET_KEY", "") or "").strip()


def _required() -> bool:
    try:
        from backend.config import settings
        return bool(int(getattr(settings, "ss_turnstile_required", 0) or 0))
    except Exception:
        return os.environ.get("SS_TURNSTILE_REQUIRED", "0") == "1"


def verify_turnstile(token: Optional[str], remote_ip: Optional[str] = None) -> Tuple[bool, str]:
    """Turnstile トークンを検証する。

    Returns: (ok, reason)
      ok=True なら検証成功（または required=False で skip された）
      ok=False の場合 reason に失敗理由
    """
    global _warned_no_secret

    secret = _secret()
    if not secret:
        if not _warned_no_secret:
            logger.warning(
                "[turnstile] SS_TURNSTILE_SECRET_KEY 未設定。検証をスキップします。"
                " 本番では必ず設定してください。"
            )
            _warned_no_secret = True
        return True, "skipped_no_secret"

    if not token:
        if _required():
            return False, "Turnstile トークンが提供されていません"
        return True, "skipped_token_empty"

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        _SITEVERIFY_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        # hardcoded Cloudflare siteverify https endpoint (_SITEVERIFY_URL).
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.error("[turnstile] siteverify request failed: %s", exc)
        return False, f"siteverify request failed: {exc}"

    if payload.get("success") is True:
        return True, "ok"
    errs = payload.get("error-codes") or []
    return False, f"Turnstile 検証失敗: {','.join(errs) or 'unknown'}"
