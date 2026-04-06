"""add task status to chat sessions

Revision ID: add_task_status
Revises: d9cbd43b62e5
Create Date: 2026-04-06 01:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_task_status"
down_revision = "d9cbd43b62e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add task status tracking fields to chat_sessions
    op.add_column("chat_sessions", sa.Column("last_task_status", sa.String(20), nullable=True))
    op.add_column("chat_sessions", sa.Column("last_task_description", sa.Text(), nullable=True))
    op.add_column("chat_sessions", sa.Column("last_task_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_sessions", sa.Column("last_task_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_sessions", "last_task_completed_at")
    op.drop_column("chat_sessions", "last_task_started_at")
    op.drop_column("chat_sessions", "last_task_description")
    op.drop_column("chat_sessions", "last_task_status")
