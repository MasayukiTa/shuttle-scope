"""refresh_tokens に successor_token_enc 列を足す (rotation 冪等化)

なぜ
----
fix/auth-session-persist: refresh の rotation は「旧 refresh を即 revoke し新しい
refresh を発行」する方式だが、ネットワーク断でクライアントが rotation 応答を受け
取れず同じ旧 refresh で再試行する / タブ複製で同時に二重に rotation が走る、と
いったケースで、旧 refresh の再提示が reuse 検知に当たり **正常利用者が即ログアウト**
されていた。

これを冪等化するため、rotation 時に発行した「後継 refresh の平文」を一定の猶予時間
(既定 60s) だけ復元できるようにする。平文のまま置くと token_hash 方針 (ハッシュのみ
保存) を破るので、SECRET_KEY から導出した鍵で Fernet 暗号化した文字列を保存する。
この列はその暗号文を入れるためのもの。

猶予内の再提示なら一族を revoke せず、保存済みの後継 refresh を復元して返す。猶予を
過ぎた再提示は従来どおり reuse 扱いで chain 全体を revoke する。

列は nullable。既存行・暗号鍵が無い環境では NULL のままで、その場合は冪等再提示を
諦めて従来の reuse 判定に倒れる (安全側)。

Revision ID: 0065
Revises: 0064
"""
from alembic import op
import sqlalchemy as sa


revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

_TABLE = "refresh_tokens"
_COLUMN = "successor_token_enc"


def _has_column(bind) -> bool:
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    return _COLUMN in cols


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_column(bind):
        return
    # SQLite はバージョンによっては drop column 不可。alembic の batch で逃がす。
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
