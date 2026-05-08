"""Host Liability Wave B: content_reports + training_dataset_records.

content_reports: CONTENT_POLICY.md / NOTICE_AND_TAKEDOWN_PROCEDURE.md に
基づく違反コンテンツ通報の永続化テーブル。匿名通報も受け付ける。
admin が triage / action をログに残す。

training_dataset_records: LEARNING_DATA_PROVENANCE.md に基づく学習データ
provenance 記録。license_type で著作権法第30条の4 / 第47条の5、明示許諾、
β-legacy 想定等を区別する。

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-08
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── content_reports ─────────────────────────────────────────────
    if "content_reports" not in inspector.get_table_names():
        op.create_table(
            "content_reports",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("subject_url", sa.String(length=500), nullable=True),
            sa.Column("subject_match_id", sa.Integer(), nullable=True),
            sa.Column("complainant_email", sa.String(length=255), nullable=True),
            sa.Column("complainant_name", sa.String(length=255), nullable=True),
            sa.Column("statement_text", sa.Text(), nullable=False),
            sa.Column("legal_basis", sa.String(length=50), nullable=True),
            # 'copyright' / 'data_protection' / 'defamation' / 'other'
            sa.Column(
                "received_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("source_ip", sa.String(length=64), nullable=True),
            # triage
            sa.Column(
                "triage_status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            ),
            # 'pending' | 'upheld' | 'rejected' | 'awaiting_info' | 'on_hold'
            sa.Column("triaged_at", sa.DateTime(), nullable=True),
            sa.Column("triaged_by_user_id", sa.Integer(), nullable=True),
            sa.Column("triage_note", sa.Text(), nullable=True),
            # action
            sa.Column("action_taken", sa.String(length=50), nullable=True),
            # 'no_action' | 'content_removed' | 'access_restricted'
            #  | 'account_suspended' | 'pending_legal'
            sa.Column("action_at", sa.DateTime(), nullable=True),
            # counter-notice
            sa.Column("counter_notice_received_at", sa.DateTime(), nullable=True),
            sa.Column("counter_notice_text", sa.Text(), nullable=True),
            sa.Column("restored_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "idx_content_reports_status",
            "content_reports",
            ["triage_status"],
        )
        op.create_index(
            "idx_content_reports_received_at",
            "content_reports",
            ["received_at"],
        )

    # ── training_dataset_records ───────────────────────────────────
    if "training_dataset_records" not in inspector.get_table_names():
        op.create_table(
            "training_dataset_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(length=100), nullable=False),
            # source URL を生で保存しない (PII / URL 自体が機微である可能性)
            sa.Column("source_url_hash", sa.String(length=64), nullable=True),
            sa.Column("acquisition_date", sa.Date(), nullable=False),
            sa.Column("license_type", sa.String(length=50), nullable=False),
            # 'granted' | 'public_domain' | 'appi_47_4' | 'appi_47_5'
            #  | 'beta_legacy_assumed_legal' | 'other'
            sa.Column("licensor_id", sa.String(length=100), nullable=True),
            sa.Column("licensor_contact", sa.String(length=255), nullable=True),
            sa.Column("scope_description", sa.String(length=500), nullable=False),
            sa.Column("verification_artefacts", sa.String(length=500), nullable=True),
            sa.Column(
                "beta_legacy_flag",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("recorded_by_user_id", sa.Integer(), nullable=False),
            sa.Column(
                "recorded_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index(
            "idx_training_dataset_records_dataset",
            "training_dataset_records",
            ["dataset_id"],
        )
        op.create_index(
            "idx_training_dataset_records_license",
            "training_dataset_records",
            ["license_type"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "training_dataset_records" in inspector.get_table_names():
        op.drop_index(
            "idx_training_dataset_records_license",
            table_name="training_dataset_records",
        )
        op.drop_index(
            "idx_training_dataset_records_dataset",
            table_name="training_dataset_records",
        )
        op.drop_table("training_dataset_records")

    if "content_reports" in inspector.get_table_names():
        op.drop_index(
            "idx_content_reports_received_at", table_name="content_reports"
        )
        op.drop_index("idx_content_reports_status", table_name="content_reports")
        op.drop_table("content_reports")
