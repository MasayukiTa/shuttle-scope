"""live_sources テーブル追加 + session_participants デバイスライフサイクル拡張

追加テーブル:
- live_sources: セッション内カメラソース管理（種別・優先度・解像度・状態）

追加カラム (session_participants):
- device_uid          : デバイス固有 ID（再接続認識用）
- approval_status     : pending / approved / rejected
- last_heartbeat      : 最終ハートビート日時
- viewer_permission   : allowed / blocked / default
- device_class        : phone / tablet / pc / camera
- display_size_class  : standard / large_tablet

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect, text
    bind = op.get_bind()
    inspector = sa_inspect(bind)

    existing_tables = inspector.get_table_names()
    participant_cols = {c["name"] for c in inspector.get_columns("session_participants")}

    # ─── live_sources テーブル作成 ─────────────────────────────────────────
    if "live_sources" not in existing_tables:
        op.execute(text("""
            CREATE TABLE live_sources (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       INTEGER NOT NULL REFERENCES shared_sessions(id),
                participant_id   INTEGER REFERENCES session_participants(id),
                source_kind      VARCHAR(20) NOT NULL,
                source_priority  INTEGER DEFAULT 4,
                source_resolution VARCHAR(20),
                source_fps       INTEGER,
                source_status    VARCHAR(20) DEFAULT 'inactive',
                suitability      VARCHAR(20) DEFAULT 'usable',
                created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))

    # ─── session_participants カラム追加 ────────────────────────────────────
    if "device_uid" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN device_uid VARCHAR(64)"))
    if "approval_status" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN approval_status VARCHAR(20) DEFAULT 'pending'"))
    if "last_heartbeat" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN last_heartbeat DATETIME"))
    if "viewer_permission" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN viewer_permission VARCHAR(20) DEFAULT 'default'"))
    if "device_class" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN device_class VARCHAR(20)"))
    if "display_size_class" not in participant_cols:
        op.execute(text("ALTER TABLE session_participants ADD COLUMN display_size_class VARCHAR(20) DEFAULT 'standard'"))

    # ─── 既存データのバックフィル ───────────────────────────────────────────
    # 既存参加者は全て承認済みとして扱う（Phase 1 以前からいるデバイス）
    op.execute(text(
        "UPDATE session_participants SET approval_status = 'approved' WHERE approval_status IS NULL"
    ))
    op.execute(text(
        "UPDATE session_participants SET viewer_permission = 'default' WHERE viewer_permission IS NULL"
    ))

    # device_class の推定（device_type から）
    op.execute(text("""
        UPDATE session_participants SET device_class = CASE
            WHEN device_type = 'iphone' THEN 'phone'
            WHEN device_type = 'ipad' THEN 'tablet'
            WHEN device_type IN ('usb_camera', 'builtin_camera') THEN 'camera'
            ELSE 'pc'
        END
        WHERE device_class IS NULL
    """))


def downgrade() -> None:
    pass
