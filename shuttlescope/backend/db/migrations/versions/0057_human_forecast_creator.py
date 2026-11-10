"""human_forecasts.creator_user_id — record who created a human forecast (G5 item #687)

Why this column exists
----------------------
Deleting a human forecast was previously allowed for anyone within the owning
team (plus admin). Item #687 decided option A: only the creator of a forecast
(within the team) or an admin may delete it. The model stored the forecaster as
a free-text name only, so there was no way to tie a row to the authenticated
user who created it. This adds a nullable creator user id.

Existing rows have no creator and cannot be backfilled (only free-text
forecaster_name exists), so they stay NULL. The delete handler treats a NULL
creator as admin-only.

Additive only: nullable column, no backfill. Mirrors 0051 (scouting_owner_team_id)
for the FK handling under SQLite (FK declared only on non-sqlite dialects; the
actual delete authorization lives in the application layer).

Revision ID: 0057
Revises: 0056
"""
from alembic import op
import sqlalchemy as sa

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

_TABLE = "human_forecasts"
_COLUMN = "creator_user_id"
_INDEX = "ix_human_forecasts_creator_user_id"
_FK = "fk_human_forecasts_creator_user_id_users"


def upgrade() -> None:
    # bootstrap 経路は Base.metadata.create_all で models どおりの表を先に作ってから
    # alembic を回すため、この列が既に存在し得る。素の add_column だと
    # "duplicate column name" で migration 全体が失敗する (0051 / 0056 と同じ理由)。
    # 存在確認してから足す。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns(_TABLE)}
    if _COLUMN not in existing:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))

    index_names = {i["name"] for i in insp.get_indexes(_TABLE)}
    if _INDEX not in index_names:
        op.create_index(_INDEX, _TABLE, [_COLUMN])

    # SQLite は ALTER TABLE ADD CONSTRAINT を持たないため FK は batch でしか足せない。
    # ここでの FK は整合性の宣言であって、削除可否の判定はアプリ側
    # (routers/human_forecast.py) が creator_user_id == ctx.user_id で行う。
    # SQLite では省略する (0051 と同方針)。
    if op.get_bind().dialect.name != "sqlite":
        fk_names = {fk["name"] for fk in insp.get_foreign_keys(_TABLE)}
        if _FK not in fk_names:
            op.create_foreign_key(
                _FK,
                _TABLE,
                "users",
                [_COLUMN],
                ["id"],
            )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if op.get_bind().dialect.name != "sqlite":
        fk_names = {fk["name"] for fk in insp.get_foreign_keys(_TABLE)}
        if _FK in fk_names:
            op.drop_constraint(_FK, _TABLE, type_="foreignkey")
    if _INDEX in {i["name"] for i in insp.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in insp.get_columns(_TABLE)}:
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(_COLUMN)
        else:
            op.drop_column(_TABLE, _COLUMN)
