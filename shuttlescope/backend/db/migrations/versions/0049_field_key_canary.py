"""フィールド暗号鍵のカナリアテーブルを追加する。

背景:
  0048 で users.totp_secret を暗号化対象にしたが、起動時の鍵チェックが
  「その場で暗号化して同じ鍵で復号する」だけだった。これは *新しく生成した
  別の鍵* でも通ってしまい、本来検出したい「鍵の取り違え」を検出できない。

  別鍵のまま起動すると:
    - 既存の暗号文 (totp_secret / conditions の自由記述) が全て復号不能
    - バックフィルが平文を別鍵で暗号化し、鍵が混在した DB になる

  そこで既知の平文を暗号化した 1 行を保存し、起動のたびに復号して一致を確認する。
  既存の暗号化データが 0 件の環境でも成立するよう、既存列ではなく専用行を使う。

行の投入はアプリ側 (field_crypto.verify_key_matches_stored_data) が行う。
migration は ss_migration ロールで走り、鍵を持たない可能性があるため
ここでは暗号化しない (0048 と同じ理由)。

Revision ID: 0049
Revises: 0048
"""
from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "field_key_canary" not in insp.get_table_names():
        op.create_table(
            "field_key_canary",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )

    # runtime ロール (ss_user) がカナリアを読み書きできるようにする。
    # 初回起動時に INSERT する必要があるため SELECT だけでは足りない。
    if bind.dialect.name == "postgresql":
        try:
            with bind.begin_nested():
                bind.execute(sa.text(
                    "GRANT SELECT, INSERT, UPDATE ON field_key_canary TO ss_user"))
        except Exception as exc:  # noqa: BLE001 - ロール未定義環境は正常系
            print(f"[migration 0049] GRANT to ss_user skipped: {exc}")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "field_key_canary" in insp.get_table_names():
        op.drop_table("field_key_canary")
