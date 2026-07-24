"""LiveKit (SFU) media-plane integration — Phase 1: access-token 発行 + room マッピング。

100試合 / 200 送信 / 400 視聴 規模に向け、現行 P2P WebRTC signaling
(`backend/ws/camera.py`) を SFU(LiveKit) ベースへ移行する土台。設計:
docs/validation/2026-06-01_rtmp_sfu_media_plane_design.md

本モジュールは **LiveKit サーバが無くても単体テスト可能**(JWT 生成/検証のみ)。
メディア本体(WebRTC/RTMP/HLS)は LiveKit が直接捌き、Cloudflare は経由しない
(制御面=CF, メディア面=SFU 直 IP の分離)。

env:
  LIVEKIT_URL          例: wss://media.example.com (フロントが接続する SFU)
  LIVEKIT_API_KEY      LiveKit API key
  LIVEKIT_API_SECRET   LiveKit API secret (JWT 署名鍵)
  SS_LIVEKIT_TOKEN_TTL access-token TTL 秒 (default 3600)
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Literal, Optional

import jwt  # PyJWT (旧 python-jose から置換: PYSEC-2026-1325 の ecdsa 依存排除)

Role = Literal["operator", "camera", "viewer"]

# ── role → LiveKit video grant ────────────────────────────────────────────
# 既存 camera.py のロール意味を継承:
#   operator: 制御権 (publish + subscribe + data)
#   camera  : 送信のみ (iOS / USB / Mavic ingress)
#   viewer  : 受信のみ (PC/tablet。phone は既定 video 無し=subscribe させない)
_ROLE_GRANTS: dict[str, dict] = {
    "operator": {"canPublish": True, "canSubscribe": True, "canPublishData": True},
    "camera": {"canPublish": True, "canSubscribe": False, "canPublishData": False},
    "viewer": {"canPublish": False, "canSubscribe": True, "canPublishData": False},
}

# session_code は英数 + 一部記号のみ許可 (room 名 injection 防止)。
_SESSION_CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_ROOM_PREFIX = "match-"


@dataclass(frozen=True)
class LiveKitConfig:
    url: str
    api_key: str
    api_secret: str
    token_ttl: int = 3600

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key and self.api_secret)


def load_config() -> LiveKitConfig:
    return LiveKitConfig(
        url=os.environ.get("LIVEKIT_URL", "").strip(),
        api_key=os.environ.get("LIVEKIT_API_KEY", "").strip(),
        api_secret=os.environ.get("LIVEKIT_API_SECRET", "").strip(),
        token_ttl=int(os.environ.get("SS_LIVEKIT_TOKEN_TTL", "3600")),
    )


def room_name_for(session_code: str) -> str:
    """match セッションコード → LiveKit room 名。検証失敗は ValueError。"""
    if not _SESSION_CODE_RE.match(session_code or ""):
        raise ValueError(f"invalid session_code: {session_code!r}")
    return f"{_ROOM_PREFIX}{session_code}"


def grants_for_role(role: str) -> dict:
    """ロール → publish/subscribe grant。未知ロールは ValueError。"""
    g = _ROLE_GRANTS.get(role)
    if g is None:
        raise ValueError(f"unknown role: {role!r}")
    return dict(g)


def issue_access_token(
    identity: str,
    session_code: str,
    role: Role,
    cfg: Optional[LiveKitConfig] = None,
    now: Optional[int] = None,
) -> str:
    """LiveKit access token (HS256 JWT) を発行する。

    claims は LiveKit 仕様: iss=api_key, sub=identity, video grant に room/roomJoin と
    publish/subscribe を載せる。署名鍵 = api_secret。
    """
    cfg = cfg or load_config()
    if not cfg.configured:
        raise RuntimeError("LiveKit is not configured (LIVEKIT_URL/API_KEY/API_SECRET)")
    if not identity:
        raise ValueError("identity required")
    room = room_name_for(session_code)
    grant = grants_for_role(role)
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": cfg.api_key,
        "sub": identity,
        "name": identity,
        "nbf": issued,
        "iat": issued,
        "exp": issued + cfg.token_ttl,
        "video": {"room": room, "roomJoin": True, **grant},
    }
    return jwt.encode(claims, cfg.api_secret, algorithm="HS256")  # PyJWT 2.x: str を返す (jose と同じ)
