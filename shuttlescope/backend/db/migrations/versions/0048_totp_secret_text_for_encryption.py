"""users.totp_secret を VARCHAR(64) → TEXT に広げる (暗号文を格納するため)。

背景:
  totp_secret (MFA の共有秘密) は平文で保存されていた。DB 単体の流出
  (バックアップ・論理ダンプ・データディレクトリ奪取) だけで攻撃者が有効な
  TOTP を生成でき、MFA が意味を失う。models.py 側で EncryptedText
  (Fernet, "v1:" 前置) に載せ替えた。

  Fernet 暗号文は 32 文字の base32 secret に対して前置込み 143 文字になるため、
  既存の VARCHAR(64) には収まらない。本 migration はその**列型変更だけ**を行う。

既存データの暗号化は行わない (意図的):
  - 本 migration は ss_migration ロールで実行され、その環境に
    SS_FIELD_ENCRYPTION_KEY があるとは限らない。鍵の無い環境で暗号化を試みると
    field_crypto はフォールバックして平文のまま書き戻し、「暗号化済み」と
    誤認される。
  - 復号可否の検証・冪等性・同時更新の考慮が必要で、マイグレーションの
    責務を超える。
  → backend/scripts/encrypt_totp_secrets.py を別途実行すること。

移行期間の互換性:
  decrypt_field() は "v1:" 前置が無い値を平文として素通しするため、列型を広げた
  段階では平文のままでも読み書きできる。バックフィル前後どちらでもアプリは動く。

Revision ID: 0048
Revises: 0047
"""
from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "users", "totp_secret",
            existing_type=sa.String(length=64),
            type_=sa.Text(),
            existing_nullable=True,
        )
    # SQLite は VARCHAR の長さを強制しないので列型変更は不要 (かつ ALTER が弱い)。
    # 新規作成時の型は models.py / database.py 側の定義に従う。


def downgrade() -> None:
    # TEXT → VARCHAR(64) に戻すと、暗号化済み (143 文字) の値は切り詰められて
    # **復元不能**になる。復号は鍵を要し、それは migration の責務ではない。
    # ダウングレードが本当に必要なら、アプリを停止した上で
    # backend/scripts/encrypt_totp_secrets.py --decrypt で平文に戻し、
    # 全件が 64 文字以内であることを確認してから手動で列型を戻すこと。
    raise RuntimeError(
        "0048 は自動 downgrade できません。totp_secret には暗号文が入っている "
        "可能性があり、VARCHAR(64) へ戻すと切り詰めで復元不能になります。"
        "アプリ停止 → encrypt_totp_secrets.py --decrypt → 全件 64 文字以内を確認 "
        "→ 手動で ALTER、の順で実施してください。"
    )
