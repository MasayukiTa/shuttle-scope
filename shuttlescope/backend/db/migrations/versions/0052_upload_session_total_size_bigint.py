"""upload_sessions.total_size を BigInteger に広げる

なぜ
----
`MAX_UPLOAD_SIZE` は 50GB (`backend/routers/uploads.py`)、サーバ録画の
クライアントは streaming の上限として 50_000_000_000 を申告する。しかし
この列は `Integer` = PostgreSQL の int4 で、上限は 2,147,483,647 (約 2.1GB)。

  50_000_000_000 > 2_147_483_647

SQLite の INTEGER は 64bit なので、開発機とテストでは通ってしまう。
本番は PostgreSQL なので、**サーバ録画の init はそこで必ず失敗する**。
「テストは緑だが本番だけ落ちる」典型で、この経路が実運用で一度も
成立していなかった理由のひとつ。

`received_count` と `total_chunks` はチャンク数なので int4 で足りる
(50GB / 64KB = 約 78 万)。`chunk_size` は 8MB 上限。よって広げるのは
`total_size` だけでよい。

Revision ID: 0052
Revises: 0051
"""
from alembic import op
import sqlalchemy as sa


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite は ALTER COLUMN TYPE を持たない。そちらの INTEGER は元々 64bit
    # なので、変更の必要が無い = 何もしないのが正しい。
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "upload_sessions",
        "total_size",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    # 2.1GB を超える行があると縮小は失敗する。実データを壊さないための
    # 素直な挙動なので、握り潰さずそのまま失敗させる。
    op.alter_column(
        "upload_sessions",
        "total_size",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
