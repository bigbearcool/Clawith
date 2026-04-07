"""add tenant_settings table

Revision ID: add_tenant_settings
Revises: add_voice_fields
Create Date: 2026-04-07

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_tenant_settings"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create tenant_settings table
    op.create_table(
        "tenant_settings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "key"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_key"),
    )

    # Create indexes
    op.create_index("ix_tenant_settings_tenant_id", "tenant_settings", ["tenant_id"])
    op.create_index("ix_tenant_settings_key", "tenant_settings", ["key"])


def downgrade() -> None:
    op.drop_index("ix_tenant_settings_key", table_name="tenant_settings")
    op.drop_index("ix_tenant_settings_tenant_id", table_name="tenant_settings")
    op.drop_table("tenant_settings")
