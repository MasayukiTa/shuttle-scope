"""Phase Pay-1: 課金 / 決済テーブル追加。

- billing_products
- billing_orders
- billing_webhook_events
- billing_entitlements

フロント完全非公開、表に出すのは Phase Pay-2 から。

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-29
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "billing_products" not in existing:
        op.create_table(
            "billing_products",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(50), nullable=False, unique=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("price_jpy", sa.Integer, nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
            sa.Column("extra_metadata", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_billing_products_code", "billing_products", ["code"], unique=True)

    if "billing_orders" not in existing:
        op.create_table(
            "billing_orders",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("public_id", sa.String(36), nullable=False, unique=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("product_id", sa.Integer, sa.ForeignKey("billing_products.id"), nullable=False),
            sa.Column("amount_jpy", sa.Integer, nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="JPY"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("payment_method", sa.String(30), nullable=True),
            sa.Column("provider", sa.String(20), nullable=True),
            sa.Column("provider_session_id", sa.String(200), nullable=True),
            sa.Column("provider_payment_id", sa.String(200), nullable=True),
            sa.Column("extra_metadata", sa.Text, nullable=True),
            sa.Column("return_url", sa.String(500), nullable=True),
            sa.Column("cancel_url", sa.String(500), nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("paid_at", sa.DateTime, nullable=True),
            sa.Column("refunded_at", sa.DateTime, nullable=True),
            sa.Column("expires_at", sa.DateTime, nullable=True),
        )
        op.create_index("ix_billing_orders_user_id", "billing_orders", ["user_id"])
        op.create_index("ix_billing_orders_status", "billing_orders", ["status"])
        op.create_index("ix_billing_orders_public_id", "billing_orders", ["public_id"], unique=True)

    if "billing_webhook_events" not in existing:
        op.create_table(
            "billing_webhook_events",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("provider", sa.String(20), nullable=False),
            sa.Column("event_id", sa.String(200), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("raw_payload", sa.Text, nullable=True),
            sa.Column("signature_verified", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
            sa.Column("related_order_id", sa.Integer, sa.ForeignKey("billing_orders.id"), nullable=True),
            sa.Column("processed_at", sa.DateTime, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index(
            "ix_billing_webhook_events_provider_event",
            "billing_webhook_events", ["provider", "event_id"], unique=True,
        )
        op.create_index(
            "ix_billing_webhook_events_processed_at",
            "billing_webhook_events", ["processed_at"],
        )

    if "billing_entitlements" not in existing:
        op.create_table(
            "billing_entitlements",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
            sa.Column("order_id", sa.Integer, sa.ForeignKey("billing_orders.id"), nullable=True),
            sa.Column("entitlement_type", sa.String(50), nullable=False),
            sa.Column("resource_type", sa.String(50), nullable=True),
            sa.Column("resource_id", sa.Integer, nullable=True),
            sa.Column("valid_from", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("valid_to", sa.DateTime, nullable=True),
            sa.Column("revoked_at", sa.DateTime, nullable=True),
            sa.Column("granted_by_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_billing_entitlements_user_id", "billing_entitlements", ["user_id"])
        op.create_index(
            "ix_billing_entitlements_resource",
            "billing_entitlements", ["resource_type", "resource_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for t in ("billing_entitlements", "billing_webhook_events", "billing_orders", "billing_products"):
        if t in existing:
            op.drop_table(t)
