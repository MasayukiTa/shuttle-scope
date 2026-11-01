"""Baseline schema: create every core table the later migrations assume.

Why this exists (finding data-01):
    Migrations 0001..0060 only ALTER pre-existing core tables (players, users,
    matches, ...); none of them CREATE those tables. On SQLite this was hidden
    because ``bootstrap_database`` runs ``Base.metadata.create_all`` before the
    Alembic upgrade. On a brand-new PostgreSQL database ``create_all`` is never
    run (DDL is Alembic-only), so ``alembic upgrade head`` from an empty
    database failed with ``NoSuchTableError: players``. This revision makes the
    migration chain self-contained: it is now the root (down_revision = None)
    and 0001 chains onto it.

Strictly additive / no-op on existing databases:
    Every ``create_table`` is guarded by ``_table_exists`` (inspector-based), so
    on any database that already has these tables -- every existing SQLite and
    PostgreSQL database, including production -- this revision does nothing.

Column shape:
    Tables are created in their current shape. The later migrations are all
    guarded (``inspector.get_columns`` / ``_table_exists`` existence checks), so
    on a fresh database they become no-ops over these tables and the resulting
    schema equals ``Base.metadata.create_all``. Types are dialect-neutral and
    Boolean server defaults use ``sa.false()`` / ``sa.true()`` (PostgreSQL
    rejects integer literals for boolean columns). Foreign-key constraints are
    intentionally omitted here: several core tables reference ``teams``, which a
    later migration (0009) creates, so emitting those FKs in the root revision
    would fail on PostgreSQL where the referenced table does not yet exist. The
    columns themselves are created; the later migrations add the FK edges on
    fresh databases and are a no-op on existing ones.

Revision ID: 0000
Revises: (none)
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0000"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    # Offline (``alembic upgrade --sql`` / as_sql) renders static SQL with no
    # live connection, so there is nothing to inspect: emit the CREATE
    # unconditionally. This is exactly the disaster-recovery / staging bootstrap
    # SQL for a brand-new database, where the tables genuinely do not exist yet.
    # Online, inspect the real bind so that on any database that already has the
    # table -- every existing SQLite and PostgreSQL database, including
    # production -- this revision is a complete no-op.
    ctx = op.get_context()
    if getattr(ctx, "as_sql", False):
        return False
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("access_logs"):
        op.create_table(
            "access_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=50), nullable=False),
            sa.Column("resource_type", sa.String(length=50), nullable=True),
            sa.Column("resource_id", sa.Integer(), nullable=True),
            sa.Column("details", sa.Text(), nullable=True),
            sa.Column("ip_addr", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("prev_hash", sa.String(length=64), nullable=True),
            sa.Column("row_hash", sa.String(length=64), nullable=True),
        )
    if not _table_exists("analysis_cache"):
        op.create_table(
            "analysis_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("cache_key", sa.String(length=200), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("analysis_type", sa.String(length=50), nullable=False),
            sa.Column("filters_json", sa.Text(), nullable=False),
            sa.Column("result_json", sa.Text(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("confidence_level", sa.Float(), nullable=False),
            sa.Column("computed_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("cache_key"),
        )
    if not _table_exists("analysis_jobs"):
        op.create_table(
            "analysis_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("job_type", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("progress", sa.Float(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("enqueued_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("worker_host", sa.String(length=120), nullable=True),
        )
    if not _table_exists("center_of_gravity"):
        op.create_table(
            "center_of_gravity",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("frame_index", sa.Integer(), nullable=False),
            sa.Column("side", sa.String(length=20), nullable=False),
            sa.Column("left_pct", sa.Float(), nullable=False),
            sa.Column("right_pct", sa.Float(), nullable=False),
            sa.Column("forward_lean", sa.Float(), nullable=False),
            sa.Column("stability_score", sa.Float(), nullable=False),
        )
    if not _table_exists("clip_cache"):
        op.create_table(
            "clip_cache",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("stroke_id", sa.Integer(), nullable=False),
            sa.Column("clip_path", sa.String(length=500), nullable=False),
            sa.Column("start_frame", sa.Integer(), nullable=False),
            sa.Column("end_frame", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
        )
    if not _table_exists("comments"):
        op.create_table(
            "comments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("session_id", sa.Integer(), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("set_id", sa.Integer(), nullable=True),
            sa.Column("rally_id", sa.Integer(), nullable=True),
            sa.Column("stroke_id", sa.Integer(), nullable=True),
            sa.Column("author_role", sa.String(length=20), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("is_flagged", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("condition_tags"):
        op.create_table(
            "condition_tags",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(length=100), nullable=False),
            sa.Column("start_date", sa.Date(), nullable=False),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column("color", sa.String(length=7), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("conditions"):
        op.create_table(
            "conditions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("measured_at", sa.Date(), nullable=False),
            sa.Column("condition_type", sa.String(length=20), nullable=False),
            sa.Column("match_id", sa.Integer(), nullable=True),
            sa.Column("weight_kg", sa.Float(), nullable=True),
            sa.Column("muscle_mass_kg", sa.Float(), nullable=True),
            sa.Column("body_fat_pct", sa.Float(), nullable=True),
            sa.Column("body_fat_mass_kg", sa.Float(), nullable=True),
            sa.Column("lean_mass_kg", sa.Float(), nullable=True),
            sa.Column("ecw_ratio", sa.Float(), nullable=True),
            sa.Column("arm_l_muscle_kg", sa.Float(), nullable=True),
            sa.Column("arm_r_muscle_kg", sa.Float(), nullable=True),
            sa.Column("leg_l_muscle_kg", sa.Float(), nullable=True),
            sa.Column("leg_r_muscle_kg", sa.Float(), nullable=True),
            sa.Column("trunk_muscle_kg", sa.Float(), nullable=True),
            sa.Column("bmr_kcal", sa.Float(), nullable=True),
            sa.Column("hooper_sleep", sa.Integer(), nullable=True),
            sa.Column("hooper_soreness", sa.Integer(), nullable=True),
            sa.Column("hooper_stress", sa.Integer(), nullable=True),
            sa.Column("hooper_fatigue", sa.Integer(), nullable=True),
            sa.Column("hooper_index", sa.Integer(), nullable=True),
            sa.Column("session_rpe", sa.Integer(), nullable=True),
            sa.Column("session_duration_min", sa.Integer(), nullable=True),
            sa.Column("session_load", sa.Integer(), nullable=True),
            sa.Column("questionnaire_json", sa.Text(), nullable=True),
            sa.Column("f1_physical", sa.Float(), nullable=True),
            sa.Column("f2_stress", sa.Float(), nullable=True),
            sa.Column("f3_mood", sa.Float(), nullable=True),
            sa.Column("f4_motivation", sa.Float(), nullable=True),
            sa.Column("f5_sleep_life", sa.Float(), nullable=True),
            sa.Column("total_score", sa.Float(), nullable=True),
            sa.Column("ccs_score", sa.Float(), nullable=True),
            sa.Column("delta_prev", sa.Float(), nullable=True),
            sa.Column("delta_3ma", sa.Float(), nullable=True),
            sa.Column("delta_28ma", sa.Float(), nullable=True),
            sa.Column("z_score", sa.Float(), nullable=True),
            sa.Column("validity_score", sa.Float(), nullable=True),
            sa.Column("validity_flag", sa.String(length=20), nullable=True),
            sa.Column("validity_flags_json", sa.Text(), nullable=True),
            sa.Column("sleep_hours", sa.Float(), nullable=True),
            sa.Column("injury_notes", sa.Text(), nullable=True),
            sa.Column("general_comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("event_bookmarks"):
        op.create_table(
            "event_bookmarks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("rally_id", sa.Integer(), nullable=True),
            sa.Column("stroke_id", sa.Integer(), nullable=True),
            sa.Column("bookmark_type", sa.String(length=30), nullable=False),
            sa.Column("video_timestamp_sec", sa.Float(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("is_reviewed", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("expert_labels"):
        op.create_table(
            "expert_labels",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("stroke_id", sa.Integer(), nullable=False),
            sa.Column("annotator_role", sa.String(length=20), nullable=False),
            sa.Column("posture_collapse", sa.String(length=20), nullable=False),
            sa.Column("weight_distribution", sa.String(length=20), nullable=False),
            sa.Column("shot_timing", sa.String(length=20), nullable=False),
            sa.Column("confidence", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
        )
    if not _table_exists("human_forecasts"):
        op.create_table(
            "human_forecasts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("forecaster_role", sa.String(length=20), nullable=False),
            sa.Column("forecaster_name", sa.String(length=100), nullable=True),
            sa.Column("predicted_outcome", sa.String(length=10), nullable=False),
            sa.Column("predicted_set_path", sa.String(length=10), nullable=True),
            sa.Column("predicted_win_probability", sa.Integer(), nullable=True),
            sa.Column("confidence_level", sa.String(length=20), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("creator_user_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("live_sources"):
        op.create_table(
            "live_sources",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("participant_id", sa.Integer(), nullable=True),
            sa.Column("source_kind", sa.String(length=20), nullable=False),
            sa.Column("source_priority", sa.Integer(), nullable=False),
            sa.Column("source_resolution", sa.String(length=20), nullable=True),
            sa.Column("source_fps", sa.Integer(), nullable=True),
            sa.Column("source_status", sa.String(length=20), nullable=False),
            sa.Column("suitability", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("match_cv_artifacts"):
        op.create_table(
            "match_cv_artifacts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("artifact_type", sa.String(length=50), nullable=False),
            sa.Column("frame_count", sa.Integer(), nullable=True),
            sa.Column("backend_used", sa.String(length=50), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("matches"):
        op.create_table(
            "matches",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("tournament", sa.String(length=200), nullable=False),
            sa.Column("tournament_level", sa.String(length=20), nullable=False),
            sa.Column("tournament_grade", sa.String(length=50), nullable=True),
            sa.Column("round", sa.String(length=50), nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("venue", sa.String(length=200), nullable=True),
            sa.Column("format", sa.String(length=30), nullable=False),
            sa.Column("player_a_id", sa.Integer(), nullable=False),
            sa.Column("player_b_id", sa.Integer(), nullable=False),
            sa.Column("partner_a_id", sa.Integer(), nullable=True),
            sa.Column("partner_b_id", sa.Integer(), nullable=True),
            sa.Column("result", sa.String(length=20), nullable=False),
            sa.Column("final_score", sa.String(length=100), nullable=True),
            sa.Column("result_source", sa.String(length=10), nullable=False, server_default='manual'),
            sa.Column("video_url", sa.String(length=500), nullable=True),
            sa.Column("video_local_path", sa.String(length=500), nullable=True),
            sa.Column("video_token", sa.String(length=36), nullable=True),
            sa.Column("video_quality", sa.String(length=20), nullable=True),
            sa.Column("camera_angle", sa.String(length=30), nullable=True),
            sa.Column("annotator_id", sa.Integer(), nullable=True),
            sa.Column("annotation_status", sa.String(length=20), nullable=False),
            sa.Column("annotation_progress", sa.Float(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("initial_server", sa.String(length=20), nullable=True),
            sa.Column("player_a_start_side", sa.String(length=10), nullable=True),
            sa.Column("competition_type", sa.String(length=30), nullable=True),
            sa.Column("created_via_quick_start", sa.Boolean(), nullable=False),
            sa.Column("metadata_status", sa.String(length=20), nullable=True),
            sa.Column("exception_reason", sa.String(length=30), nullable=True),
            sa.Column("captured_minor_flag", sa.Boolean(), nullable=True),
            sa.Column("owner_team_id", sa.Integer(), nullable=True),
            sa.Column("is_public_pool", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_demo_public", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("home_team_id", sa.Integer(), nullable=True),
            sa.Column("away_team_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("uuid"),
            sa.UniqueConstraint("video_token"),
        )
    if not _table_exists("player_page_access"):
        op.create_table(
            "player_page_access",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("page_key", sa.String(length=50), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("team_name", sa.String(length=100), nullable=True),
            sa.Column("granted_by_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("players"):
        op.create_table(
            "players",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("name_en", sa.String(length=100), nullable=True),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("scouting_owner_team_id", sa.Integer(), nullable=True),
            sa.Column("nationality", sa.String(length=50), nullable=True),
            sa.Column("dominant_hand", sa.String(length=10), nullable=True),
            sa.Column("birth_year", sa.Integer(), nullable=True),
            sa.Column("world_ranking", sa.Integer(), nullable=True),
            sa.Column("is_target", sa.Boolean(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("profile_status", sa.String(length=20), nullable=True),
            sa.Column("needs_review", sa.Boolean(), nullable=False),
            sa.Column("created_via_quick_start", sa.Boolean(), nullable=False),
            sa.Column("organization", sa.String(length=200), nullable=True),
            sa.Column("aliases", sa.Text(), nullable=True),
            sa.Column("name_normalized", sa.String(length=200), nullable=True),
            sa.Column("scouting_notes", sa.Text(), nullable=True),
            sa.Column("team_history", sa.Text(), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("pose_frames"):
        op.create_table(
            "pose_frames",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("frame_index", sa.Integer(), nullable=False),
            sa.Column("ts_sec", sa.Float(), nullable=False),
            sa.Column("side", sa.String(length=20), nullable=False),
            sa.Column("landmarks_json", sa.Text(), nullable=False),
        )
    if not _table_exists("pre_match_observations"):
        op.create_table(
            "pre_match_observations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("observation_type", sa.String(length=50), nullable=False),
            sa.Column("observation_value", sa.String(length=100), nullable=False),
            sa.Column("confidence_level", sa.String(length=20), nullable=False),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.String(length=50), nullable=True),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("public_inquiries"):
        op.create_table(
            "public_inquiries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("organization", sa.String(length=160), nullable=True),
            sa.Column("role", sa.String(length=80), nullable=True),
            sa.Column("contact_reference", sa.String(length=200), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("admin_note", sa.Text(), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=400), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("rallies"):
        op.create_table(
            "rallies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("set_id", sa.Integer(), nullable=False),
            sa.Column("rally_num", sa.Integer(), nullable=False),
            sa.Column("server", sa.String(length=20), nullable=False),
            sa.Column("winner", sa.String(length=20), nullable=False),
            sa.Column("end_type", sa.String(length=30), nullable=False),
            sa.Column("rally_length", sa.Integer(), nullable=False),
            sa.Column("duration_sec", sa.Float(), nullable=True),
            sa.Column("score_a_before", sa.Integer(), nullable=False),
            sa.Column("score_b_before", sa.Integer(), nullable=False),
            sa.Column("score_a_after", sa.Integer(), nullable=False),
            sa.Column("score_b_after", sa.Integer(), nullable=False),
            sa.Column("is_deuce", sa.Boolean(), nullable=False),
            sa.Column("video_timestamp_start", sa.Float(), nullable=True),
            sa.Column("video_timestamp_end", sa.Float(), nullable=True),
            sa.Column("is_skipped", sa.Boolean(), nullable=False),
            sa.Column("annotation_mode", sa.String(length=30), nullable=True),
            sa.Column("review_status", sa.String(length=20), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("jti", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("replaced_by_jti", sa.String(length=36), nullable=True),
            sa.UniqueConstraint("jti"),
        )
    if not _table_exists("revoked_tokens"):
        op.create_table(
            "revoked_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("jti", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("jti"),
        )
    if not _table_exists("session_participants"):
        op.create_table(
            "session_participants",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("device_name", sa.String(length=100), nullable=True),
            sa.Column("joined_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("is_connected", sa.Boolean(), nullable=False),
            sa.Column("device_type", sa.String(length=20), nullable=True),
            sa.Column("connection_role", sa.String(length=30), nullable=False),
            sa.Column("source_capability", sa.String(length=20), nullable=True),
            sa.Column("video_receive_enabled", sa.Boolean(), nullable=False),
            sa.Column("authenticated_at", sa.DateTime(), nullable=True),
            sa.Column("connection_state", sa.String(length=20), nullable=False),
            sa.Column("device_uid", sa.String(length=64), nullable=True),
            sa.Column("approval_status", sa.String(length=20), nullable=False),
            sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
            sa.Column("viewer_permission", sa.String(length=20), nullable=False),
            sa.Column("device_class", sa.String(length=20), nullable=True),
            sa.Column("display_size_class", sa.String(length=20), nullable=False),
            sa.Column("ws_token_hash", sa.String(length=64), nullable=True),
            sa.Column("ws_token_expires_at", sa.DateTime(), nullable=True),
        )
    if not _table_exists("sets"):
        op.create_table(
            "sets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("set_num", sa.Integer(), nullable=False),
            sa.Column("winner", sa.String(length=20), nullable=True),
            sa.Column("score_a", sa.Integer(), nullable=False),
            sa.Column("score_b", sa.Integer(), nullable=False),
            sa.Column("duration_min", sa.Float(), nullable=True),
            sa.Column("is_deuce", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("shared_sessions"):
        op.create_table(
            "shared_sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("session_code", sa.String(length=10), nullable=False),
            sa.Column("created_by_role", sa.String(length=20), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_broadcast_at", sa.DateTime(), nullable=True),
            sa.Column("password_hash", sa.String(length=128), nullable=True),
            sa.UniqueConstraint("session_code"),
        )
    if not _table_exists("shot_inferences"):
        op.create_table(
            "shot_inferences",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("stroke_id", sa.Integer(), nullable=False),
            sa.Column("shot_type", sa.String(length=30), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("model_version", sa.String(length=40), nullable=False),
        )
    if not _table_exists("shuttle_tracks"):
        op.create_table(
            "shuttle_tracks",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("match_id", sa.Integer(), nullable=False),
            sa.Column("frame_index", sa.Integer(), nullable=False),
            sa.Column("ts_sec", sa.Float(), nullable=False),
            sa.Column("x", sa.Float(), nullable=True),
            sa.Column("y", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False),
        )
    if not _table_exists("strokes"):
        op.create_table(
            "strokes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("uuid", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("source_device_id", sa.String(length=100), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=True),
            sa.Column("rally_id", sa.Integer(), nullable=False),
            sa.Column("stroke_num", sa.Integer(), nullable=False),
            sa.Column("player", sa.String(length=20), nullable=False),
            sa.Column("shot_type", sa.String(length=30), nullable=False),
            sa.Column("shot_quality", sa.String(length=20), nullable=True),
            sa.Column("hit_x", sa.Float(), nullable=True),
            sa.Column("hit_y", sa.Float(), nullable=True),
            sa.Column("land_x", sa.Float(), nullable=True),
            sa.Column("land_y", sa.Float(), nullable=True),
            sa.Column("player_x", sa.Float(), nullable=True),
            sa.Column("player_y", sa.Float(), nullable=True),
            sa.Column("opponent_x", sa.Float(), nullable=True),
            sa.Column("opponent_y", sa.Float(), nullable=True),
            sa.Column("opponent_contact_x", sa.Float(), nullable=True),
            sa.Column("opponent_contact_y", sa.Float(), nullable=True),
            sa.Column("player_contact_x", sa.Float(), nullable=True),
            sa.Column("player_contact_y", sa.Float(), nullable=True),
            sa.Column("return_target_x", sa.Float(), nullable=True),
            sa.Column("return_target_y", sa.Float(), nullable=True),
            sa.Column("hit_zone", sa.String(length=5), nullable=True),
            sa.Column("hit_zone_source", sa.String(length=10), nullable=True),
            sa.Column("hit_zone_cv_original", sa.String(length=5), nullable=True),
            sa.Column("land_zone", sa.String(length=5), nullable=True),
            sa.Column("land_zone_source", sa.String(length=16), nullable=True),
            sa.Column("is_backhand", sa.Boolean(), nullable=False),
            sa.Column("is_around_head", sa.Boolean(), nullable=False),
            sa.Column("above_net", sa.Boolean(), nullable=True),
            sa.Column("is_cross", sa.Boolean(), nullable=False),
            sa.Column("timestamp_sec", sa.Float(), nullable=True),
            sa.Column("return_quality", sa.String(length=20), nullable=True),
            sa.Column("contact_height", sa.String(length=20), nullable=True),
            sa.Column("contact_zone", sa.String(length=20), nullable=True),
            sa.Column("movement_burden", sa.String(length=20), nullable=True),
            sa.Column("movement_direction", sa.String(length=20), nullable=True),
            sa.Column("epv", sa.Float(), nullable=True),
            sa.Column("shot_influence", sa.Float(), nullable=True),
            sa.Column("source_method", sa.String(length=20), nullable=True),
            sa.UniqueConstraint("uuid"),
        )
    if not _table_exists("sync_conflicts"):
        op.create_table(
            "sync_conflicts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("record_table", sa.String(length=50), nullable=False),
            sa.Column("record_uuid", sa.String(length=36), nullable=False),
            sa.Column("import_device", sa.String(length=100), nullable=True),
            sa.Column("import_updated_at", sa.String(length=30), nullable=True),
            sa.Column("local_updated_at", sa.String(length=30), nullable=True),
            sa.Column("incoming_snapshot", sa.Text(), nullable=True),
            sa.Column("reason", sa.String(length=200), nullable=False),
            sa.Column("resolution", sa.String(length=20), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("upload_sessions"):
        op.create_table(
            "upload_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("participant_id", sa.Integer(), nullable=True),
            sa.Column("match_id", sa.Integer(), nullable=True),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("mime_type", sa.String(length=100), nullable=True),
            sa.Column("total_size", sa.BigInteger(), nullable=False),
            sa.Column("chunk_size", sa.Integer(), nullable=False),
            sa.Column("total_chunks", sa.Integer(), nullable=False),
            sa.Column("received_bitmap", sa.LargeBinary(), nullable=False),
            sa.Column("received_count", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("final_path", sa.Text(), nullable=True),
            sa.Column("streaming", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("hashed_credential", sa.String(length=128), nullable=True),
            sa.Column("display_name", sa.String(length=100), nullable=True),
            sa.Column("team_name", sa.String(length=100), nullable=True),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default='0'),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("totp_secret", sa.Text(), nullable=True),
            sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("email_verified_at", sa.DateTime(), nullable=True),
            sa.Column("awaiting_admin_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("consent_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.UniqueConstraint("username"),
            sa.UniqueConstraint("email"),
        )


def downgrade() -> None:
    # Root revision. Downgrading past the baseline would drop the whole schema;
    # intentionally a no-op so a stray ``downgrade base`` cannot destroy data.
    pass
