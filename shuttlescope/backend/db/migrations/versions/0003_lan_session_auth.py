"""LAN セッション認証・デバイス制御フィールドを追加

追加カラム:
- shared_sessions.password_hash         : PBKDF2-SHA256 ハッシュ
- session_participants.device_type      : iphone/ipad/pc/usb_camera/builtin_camera
- session_participants.connection_role  : viewer/coach/analyst/camera_candidate/active_camera
- session_participants.source_capability: camera/viewer/none
- session_participants.video_receive_enabled : 映像受信許可フラグ
- session_participants.authenticated_at : 認証日時
- session_participants.connection_state : idle/receiving_video/sending_video

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect, text
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    session_cols = {c["name"] for c in inspector.get_columns("shared_sessions")}
    participant_cols = {c["name"] for c in inspector.get_columns("session_participants")}

    # shared_sessions へのカラム追加
    if "password_hash" not in session_cols:
        op.execute(text("ALTER TABLE shared_sessions ADD COLUMN password_hash VARCHAR(128)"))

    # session_participants へのカラム追加
    if "device_type" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN device_type VARCHAR(20)"))
    if "connection_role" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN connection_role VARCHAR(30)"))
    if "source_capability" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN source_capability VARCHAR(20)"))
    if "video_receive_enabled" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN video_receive_enabled BOOLEAN DEFAULT 0"))
    if "authenticated_at" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN authenticated_at DATETIME"))
    if "connection_state" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN connection_state VARCHAR(20)"))

    # 既存参加者のバックフィル
    op.execute(text(
        "UPDATE session_participants SET connection_role = 'viewer' WHERE connection_role IS NULL"
    ))
    op.execute(text(
        "UPDATE session_participants SET connection_state = 'idle' WHERE connection_state IS NULL"
    ))


def downgrade() -> None:
    # カラム削除の後退は不要
    pass
