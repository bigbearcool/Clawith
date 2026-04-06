"""add streaming_tool_calls_unreliable to llm_models

Revision ID: add_stream_tool_unreliable
Revises: add_task_status
Create Date: 2026-04-06

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_stream_tool_unreliable"
down_revision = "add_task_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_models", sa.Column("streaming_tool_calls_unreliable", sa.Boolean(), nullable=False, server_default="false")
    )


def downgrade() -> None:
    op.drop_column("llm_models", "streaming_tool_calls_unreliable")
