"""Drop FK constraint on access_logs.user_id (audit append-only).

Round 233 R233-A で発見した audit chain 破損問題への対応。
旧設計は `access_logs.user_id` に `users.id` への FK 制約を持っていたが、
user 削除時に FK 違反を回避するため `delete_user` で
`UPDATE access_logs SET user_id = NULL WHERE user_id = :uid` を実行していた。
この UPDATE で row の canonical bytes が変わり HMAC chain が破損する
(既に first_bad_id=466 で chain 破損が観測された)。

audit log は append-only な改ざん検出ログである一方、FK 制約は user 削除時の
referential integrity を要求する — この 2 つは設計的に矛盾する。
audit の本義 (一度書いたら変更しない) を優先し、FK 制約を撤廃する。

これにより以降の user 削除では access_logs.user_id をそのまま残せるので
HMAC chain は維持される (orphan integer reference が発生するが、user_id は
あくまで監査文脈の参照であり整合性は HMAC chain で保証される)。

注意: 既存の broken segment (id 466 以降の NULL 化された行) はこの migration
では修復しない (既存値の改竄になるため)。chain は新規 INSERT 以降 valid に
戻る。verify_chain は first_bad_id を返し続けるが、それは過去の修復可能な
破損として運用で受容する。

Revision ID: 0026
Revises: 0025
Create Date: 2026-05-09
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels = None
depends_on = None


def _find_fk_name(table_name: str, column: str, ref_table: str) -> str | None:
    """名前で FK を直接 drop できないバージョン用。inspector で見つける。"""
    insp = sa.inspect(op.get_bind())
    for fk in insp.get_foreign_keys(table_name):
        if column in (fk.get("constrained_columns") or []) and fk.get("referred_table") == ref_table:
            return fk.get("name")
    return None


def upgrade() -> None:
    """access_logs.user_id の FK を drop。column 自体 (Integer NULLABLE) は保持する。"""
    # FK 制約名は環境差があるので inspector 経由で特定する。
    fk_name = _find_fk_name("access_logs", "user_id", "users")
    if fk_name:
        # PostgreSQL: ALTER TABLE access_logs DROP CONSTRAINT <fk_name>
        # SQLite: batch_alter_table で再作成 (ALTER DROP CONSTRAINT 非対応)
        bind = op.get_bind()
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("access_logs") as batch_op:
                # SQLite はバッチで table を再作成、FK 構成だけ外す
                batch_op.drop_constraint(fk_name, type_="foreignkey")
        else:
            op.drop_constraint(fk_name, "access_logs", type_="foreignkey")


def downgrade() -> None:
    """FK を復旧。column type は Integer NULLABLE のまま。"""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("access_logs") as batch_op:
            batch_op.create_foreign_key(
                "fk_access_logs_user_id_users",
                "users",
                ["user_id"],
                ["id"],
            )
    else:
        op.create_foreign_key(
            "fk_access_logs_user_id_users",
            "access_logs",
            "users",
            ["user_id"],
            ["id"],
        )
