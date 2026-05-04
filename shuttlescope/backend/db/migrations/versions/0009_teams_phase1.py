"""Phase B-1: teams テーブル追加 + users.team_id 追加 + testチーム初期化

チーム境界（owner_team / リーク防止）導入の第一歩。
- teams テーブル新設（id / uuid / display_id ユニーク / name / is_independent）
- users.team_id 追加（nullable、B-3 で NOT NULL 化予定）
- 既存運用継続のため "testチーム" を 1 件だけ自動投入（display_id="TEST-0001"）
- testtest ユーザが存在する場合は testチーム に紐付け

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-26
"""
from datetime import datetime
from typing import Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    # ── teams テーブル ────────────────────────────────────────────────────────
    if "teams" not in tables:
        op.create_table(
            "teams",
            sa.Column("id",          sa.Integer(),    primary_key=True, autoincrement=True),
            sa.Column("uuid",        sa.String(36),   nullable=False),
            sa.Column("display_id",  sa.String(64),   nullable=True),
            sa.Column("name",        sa.String(100),  nullable=False),
            sa.Column("short_name",  sa.String(50),   nullable=True),
            sa.Column("is_independent", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes",       sa.Text(),       nullable=True),
            sa.Column("created_at",  sa.DateTime(),   nullable=False),
            sa.Column("updated_at",  sa.DateTime(),   nullable=False),
            sa.Column("deleted_at",  sa.DateTime(),   nullable=True),
        )
        op.create_index("ix_teams_uuid",       "teams", ["uuid"],       unique=True)
        op.create_index("ix_teams_display_id", "teams", ["display_id"], unique=True)

    # ── 初期チーム: testチーム ────────────────────────────────────────────────
    teams_t = sa.table(
        "teams",
        sa.column("id", sa.Integer),
        sa.column("uuid", sa.String),
        sa.column("display_id", sa.String),
        sa.column("name", sa.String),
        sa.column("is_independent", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    existing = bind.execute(sa.text("SELECT id FROM teams WHERE display_id = :d"), {"d": "TEST-0001"}).fetchone()
    if not existing:
        now = datetime.utcnow()
        bind.execute(
            sa.insert(teams_t).values(
                uuid=str(uuid4()),
                display_id="TEST-0001",
                name="testチーム",
                is_independent=False,
                created_at=now,
                updated_at=now,
            )
        )

    # ── users.team_id 列追加 ──────────────────────────────────────────────────
    # SQLite は ADD COLUMN with FK 制約をサポートしないため batch_alter_table を使う
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "team_id" not in user_cols:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "team_id",
                    sa.Integer(),
                    sa.ForeignKey("teams.id", name="fk_users_team_id_teams"),
                    nullable=True,
                ),
            )
        op.create_index("ix_users_team_id", "users", ["team_id"])

    # ── testtest ユーザを testチーム に紐付け ────────────────────────────────
    test_team = bind.execute(sa.text("SELECT id FROM teams WHERE display_id = :d"), {"d": "TEST-0001"}).fetchone()
    if test_team:
        team_id = test_team[0]
        bind.execute(
            sa.text("UPDATE users SET team_id = :tid WHERE username = :u AND (team_id IS NULL)"),
            {"tid": team_id, "u": "testtest"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_cols = {c["name"] for c in inspector.get_columns("users")}
    if "team_id" in user_cols:
        try:
            op.drop_index("ix_users_team_id", table_name="users")
        except Exception:
            pass
        op.drop_column("users", "team_id")
    tables = inspector.get_table_names()
    if "teams" in tables:
        try:
            op.drop_index("ix_teams_display_id", table_name="teams")
            op.drop_index("ix_teams_uuid",       table_name="teams")
        except Exception:
            pass
        op.drop_table("teams")
