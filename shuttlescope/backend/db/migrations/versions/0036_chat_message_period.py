"""Add date_from / date_to columns on chat_messages.

Growth Advisor チャットでユーザがメッセージに添付した分析対象期間
(parsePeriod() で抽出された YYYY-MM-DD 範囲) を永続化するためのカラム。
両カラム NULL 可。文字列で保存 (DB 移植性のため DATE ではなく VARCHAR(10))。

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def _has_column(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("chat_messages", "date_from"):
        op.add_column(
            "chat_messages",
            sa.Column("date_from", sa.String(10), nullable=True),
        )
    if not _has_column("chat_messages", "date_to"):
        op.add_column(
            "chat_messages",
            sa.Column("date_to", sa.String(10), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        try:
            batch.drop_column("date_to")
        except Exception:
            pass
        try:
            batch.drop_column("date_from")
        except Exception:
            pass
