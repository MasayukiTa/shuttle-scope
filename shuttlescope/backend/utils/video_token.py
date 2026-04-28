"""Match.video_token の生成・解決ユーティリティ。

video_token の用途:
  - /api/videos/{token}/stream の不透明キー
  - 生のファイルパスを API レスポンスに含めない
  - app://video/{token} (Electron protocol) からバックエンドストリームへの参照

セキュリティ要件:
  - トークンは推測困難（UUID4 hex = 128bit）
  - DB UNIQUE インデックスで重複排除済み
  - 検証時は必ず DB lookup（クライアント生成や hash decoding は不可）
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from backend.db.models import Match
from backend.utils.path_jail import is_allowed_video_path

# UUID4 hex 形式のトークン（32 文字、英小文字 + 数字）
_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


def new_token() -> str:
    """新規 video_token を生成する（UUID4 hex 32 文字）。"""
    return uuid.uuid4().hex


def is_valid_token_format(token: str) -> bool:
    """トークンが UUID4 hex 形式かを検証する（DB lookup なし）。"""
    return bool(_TOKEN_RE.match(token or ""))


def ensure_token(db: Session, match: Match) -> str:
    """Match に video_token がなければ生成し DB に書き込む。既存トークンを返す。"""
    if match.video_token:
        return match.video_token
    match.video_token = new_token()
    db.flush()
    return match.video_token


def resolve_token_to_path(db: Session, token: str) -> Optional[Tuple[Match, Path]]:
    """video_token から (Match, 実ファイルパス) を解決する。

    保証:
      - トークン形式の事前検証（推測総当たり耐性）
      - path_jail で許可ルート外パスをブロック
      - localfile:/// プレフィックスを正規化

    返り値: 解決失敗時は None。
    """
    if not is_valid_token_format(token):
        return None
    match = db.query(Match).filter(Match.video_token == token).one_or_none()
    if match is None or not match.video_local_path:
        return None
    raw = match.video_local_path
    if raw.startswith("localfile:///"):
        raw = raw[len("localfile:///"):]
    if raw.startswith("server://"):
        # サーバー保管動画（将来対応）。現状は localfile 系のみ受け付ける
        return None
    path = Path(raw)
    if not path.exists() or not path.is_file():
        return None
    if not is_allowed_video_path(path):
        return None
    return match, path


def video_filename_for(match: Match) -> Optional[str]:
    """Match の動画ファイル名（パスを露出しない表示用）を返す。"""
    if not match.video_local_path:
        return None
    raw = match.video_local_path
    if raw.startswith("localfile:///"):
        raw = raw[len("localfile:///"):]
    return Path(raw).name or None
