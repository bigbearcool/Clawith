"""Add identity_contacts and identity_bindings tables

Revision ID: 20260409_contacts
Revises: 09ec4c868154
Create Date: 2026-04-09

This migration adds:
1. New columns to identities table: phone_verified, primary_email, primary_phone
2. identity_contacts table: Multiple contact methods per identity
3. identity_bindings table: Channel identity bindings for cross-platform user resolution
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision: str = "20260409_contacts"
down_revision: Union[str, None] = "09ec4c868154"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # 1. Add new columns to identities table
    identities_columns = [c["name"] for c in inspector.get_columns("identities")]

    if "phone_verified" not in identities_columns:
        op.add_column("identities", sa.Column("phone_verified", sa.Boolean(), server_default="false", nullable=False))

    if "primary_email" not in identities_columns:
        op.add_column("identities", sa.Column("primary_email", sa.String(255), nullable=True))
        op.create_index("ix_identities_primary_email", "identities", ["primary_email"])

    if "primary_phone" not in identities_columns:
        op.add_column("identities", sa.Column("primary_phone", sa.String(50), nullable=True))
        op.create_index("ix_identities_primary_phone", "identities", ["primary_phone"])

    # 2. Create identity_contacts table
    tables = inspector.get_table_names()
    if "identity_contacts" not in tables:
        op.create_table(
            "identity_contacts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "identity_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("contact_type", sa.String(20), nullable=False),
            sa.Column("contact_value", sa.String(255), nullable=False),
            sa.Column("purpose", sa.String(20), server_default="verified", nullable=False),
            sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source", sa.String(50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("contact_type", "contact_value", name="uq_identity_contact_value"),
        )
        op.create_index("ix_identity_contacts_contact_value", "identity_contacts", ["contact_value"])
        op.create_index("ix_identity_contacts_identity_type", "identity_contacts", ["identity_id", "contact_type"])

    # 3. Create identity_bindings table
    if "identity_bindings" not in tables:
        op.create_table(
            "identity_bindings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "identity_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("identities.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("provider_type", sa.String(20), nullable=False),
            sa.Column("provider_user_id", sa.String(100), nullable=False),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("mobile", sa.String(50), nullable=True),
            sa.Column("raw_data", postgresql.JSON, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.UniqueConstraint("provider_type", "provider_user_id", name="uq_identity_binding_provider_user"),
        )
        op.create_index("ix_identity_bindings_provider_type", "identity_bindings", ["provider_type"])
        op.create_index("ix_identity_bindings_provider_user_id", "identity_bindings", ["provider_user_id"])
        op.create_index("ix_identity_bindings_email", "identity_bindings", ["email"])
        op.create_index("ix_identity_bindings_mobile", "identity_bindings", ["mobile"])
        op.create_index(
            "ix_identity_bindings_provider_lookup", "identity_bindings", ["provider_type", "provider_user_id"]
        )


def downgrade() -> None:
    # Drop identity_bindings table
    op.drop_index("ix_identity_bindings_provider_lookup", "identity_bindings")
    op.drop_index("ix_identity_bindings_mobile", "identity_bindings")
    op.drop_index("ix_identity_bindings_email", "identity_bindings")
    op.drop_index("ix_identity_bindings_provider_user_id", "identity_bindings")
    op.drop_index("ix_identity_bindings_provider_type", "identity_bindings")
    op.drop_table("identity_bindings")

    # Drop identity_contacts table
    op.drop_index("ix_identity_contacts_identity_type", "identity_contacts")
    op.drop_index("ix_identity_contacts_contact_value", "identity_contacts")
    op.drop_table("identity_contacts")

    # Drop new columns from identities
    op.drop_index("ix_identities_primary_phone", "identities")
    op.drop_index("ix_identities_primary_email", "identities")
    op.drop_column("identities", "primary_phone")
    op.drop_column("identities", "primary_email")
    op.drop_column("identities", "phone_verified")
