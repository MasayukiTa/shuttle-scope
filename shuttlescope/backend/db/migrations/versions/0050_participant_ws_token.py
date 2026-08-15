"""session_participants に参加者スコープの WS 資格情報を追加する。

背景:
  カメラ signaling WS はどのロールにもアプリの JWT を要求していた。しかし
  カメラを担う iOS 端末はアプリのアカウントを持たず、想定 UX は
  「QR を読む → セッションパスワードを入れる → カメラになる」である。
  結果として、その経路は本番構成で一度も成立していなかった。

  そこで join (セッションパスワード検証済み) の成功時に、その参加者だけを
  表す資格情報を発行する。JWT の代替ではなく、対象は
  「この session の この participant」に限定される。

  平文は join 応答で一度だけ返し、DB には SHA-256 のみ置く。
  失効は hash を NULL にするだけでよい (reject / 削除 / 期限切れ)。

Revision ID: 0050
Revises: 0049
"""
from alembic import op
import sqlalchemy as sa


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("ws_token_hash", sa.String(length=64)),
    ("ws_token_expires_at", sa.DateTime()),
)


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("session_participants")}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column("session_participants", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("session_participants")}
    for name, _type in _COLUMNS:
        if name in existing:
            op.drop_column("session_participants", name)
