"""players.scouting_owner_team_id — external (opponent) players owned by a team

Why this column exists
----------------------
Scouting an opponent means annotating a match between two players who are not on
our own team. Until now that was impossible for every non-admin actor:

  - matches.py refused to create a match with no own-team player
  - players.py refused to let an analyst register a player of another team
  - GET /players returned own-team players only, so even an existing record
    could not be selected as an analysis subject

Simply widening those checks to "any player" would expose other teams' rosters
and their annotated data, which the tenant boundary exists to prevent.

Instead we add a second, explicit form of ownership: a player record may be an
*external* one that a team registered for scouting. It belongs to no roster
(team_id stays NULL) but is owned, and therefore visible, only to the team that
registered it. Cross-team visibility is unchanged.

Revision ID: 0051
Revises: 0050
"""
from alembic import op
import sqlalchemy as sa


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


_COLUMN = "scouting_owner_team_id"
_INDEX = "ix_players_scouting_owner_team_id"


def upgrade() -> None:
    # bootstrap 経路は先に Base.metadata.create_all で models どおりの表を作ってから
    # alembic を回す。その場合この列は既に存在するので、素の add_column だと
    # "duplicate column name" で migration 全体が失敗する (0050 も同じ理由で
    # inspector ガードを持っている)。存在確認してから足す。
    insp = sa.inspect(op.get_bind())
    existing = {c["name"] for c in insp.get_columns("players")}
    if _COLUMN not in existing:
        op.add_column("players", sa.Column(_COLUMN, sa.Integer(), nullable=True))

    index_names = {i["name"] for i in insp.get_indexes("players")}
    if _INDEX not in index_names:
        op.create_index(_INDEX, "players", [_COLUMN])

    # SQLite は ALTER TABLE ADD CONSTRAINT を持たないため、FK は batch でしか
    # 足せない。ここでの FK は整合性の宣言であって、可視性の判定は
    # アプリ側 (can_see_scouting_players) が行う。SQLite では省略する。
    if op.get_bind().dialect.name != "sqlite":
        fk_names = {fk["name"] for fk in insp.get_foreign_keys("players")}
        if "fk_players_scouting_owner_team_id_teams" not in fk_names:
            op.create_foreign_key(
                "fk_players_scouting_owner_team_id_teams",
                "players",
                "teams",
                [_COLUMN],
                ["id"],
            )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if op.get_bind().dialect.name != "sqlite":
        fk_names = {fk["name"] for fk in insp.get_foreign_keys("players")}
        if "fk_players_scouting_owner_team_id_teams" in fk_names:
            op.drop_constraint(
                "fk_players_scouting_owner_team_id_teams", "players", type_="foreignkey"
            )
    if _INDEX in {i["name"] for i in insp.get_indexes("players")}:
        op.drop_index(_INDEX, table_name="players")
    if _COLUMN in {c["name"] for c in insp.get_columns("players")}:
        op.drop_column("players", _COLUMN)
