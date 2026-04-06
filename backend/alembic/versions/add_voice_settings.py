"""add voice settings to agents and tencent voice to llm_models

Revision ID: add_voice_settings
Revises: add_stream_tool_unreliable
Create Date: 2026-04-06

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_voice_settings"
down_revision = "add_stream_tool_unreliable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add voice settings to agents
    op.add_column("agents", sa.Column("voice_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agents", sa.Column("voice_type", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("voice_speed", sa.Float(), nullable=False, server_default="0.0"))
    op.add_column("agents", sa.Column("voice_volume", sa.Float(), nullable=False, server_default="0.0"))

    # Add Tencent Cloud Voice settings to llm_models
    op.add_column("llm_models", sa.Column("tencent_secret_id", sa.String(100), nullable=True))
    op.add_column("llm_models", sa.Column("tencent_secret_key", sa.String(100), nullable=True))


def downgrade() -> None:
    # Remove voice settings from agents
    op.drop_column("agents", "voice_volume")
    op.drop_column("agents", "voice_speed")
    op.drop_column("agents", "voice_type")
    op.drop_column("agents", "voice_enabled")

    # Remove Tencent Cloud Voice settings from llm_models
    op.drop_column("llm_models", "tencent_secret_key")
    op.drop_column("llm_models", "tencent_secret_id")
