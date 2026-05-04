"""players.dominant_hand を nullable / VARCHAR(10) に再構成

問題:
- 旧 SQLite DB では dominant_hand が VARCHAR(1) NOT NULL のまま残っている
- ORM 定義は String(10) nullable=True だが、既存 DB のスキーマとずれている
- コード側で "unknown" を渡して回避していたが、NULL を直接設定できない

対応:
- SQLite は ALTER COLUMN を非対応のため Alembic batch モードでテーブル再構成
- VARCHAR(1) NOT NULL → VARCHAR(10) NULL に変更
- 空文字 ('') の値は NULL に正規化

Revision ID: 0001
Revises: (none)
Create Date: 2026-04-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table: SQLite でテーブル再構成を安全に行う
    # Alembic が以下を自動実行:
    #   1. 新スキーマで一時テーブルを作成
    #   2. 既存データをコピー（空文字 '' → NULL に正規化）
    #   3. 元テーブルを削除
    #   4. 一時テーブルをリネーム
    with op.batch_alter_table("players", schema=None) as batch_op:
        batch_op.alter_column(
            "dominant_hand",
            existing_type=sa.String(1),
            type_=sa.String(10),
            nullable=True,
            existing_nullable=False,
        )

    # 空文字 '' は NULL に正規化（'R'/'L'/'unknown' には触らない）
    op.execute("UPDATE players SET dominant_hand = NULL WHERE dominant_hand = ''")


def downgrade() -> None:
    # nullable 化の後退は不要（データが欠損する可能性があるため実装しない）
    pass
