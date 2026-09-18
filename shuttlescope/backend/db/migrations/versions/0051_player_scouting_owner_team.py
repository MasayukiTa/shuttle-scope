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


def upgrade() -> None:
    op.add_column(
        "players",
        sa.Column("scouting_owner_team_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_players_scouting_owner_team_id",
        "players",
        ["scouting_owner_team_id"],
    )
    op.create_foreign_key(
        "fk_players_scouting_owner_team_id_teams",
        "players",
        "teams",
        ["scouting_owner_team_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_players_scouting_owner_team_id_teams", "players", type_="foreignkey"
    )
    op.drop_index("ix_players_scouting_owner_team_id", table_name="players")
    op.drop_column("players", "scouting_owner_team_id")
