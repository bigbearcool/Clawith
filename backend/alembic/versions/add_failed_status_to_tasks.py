"""Add failed status and failed_reason field to tasks

Revision ID: add_failed_status
Revises: d9cbd43b62e5
Create Date: 2026-04-06 09:20:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "add_failed_status"
down_revision = "d9cbd43b62e5"
branch_labels = None
depends_on = None


def upgrade():
    # Add failed_reason column
    op.add_column("tasks", sa.Column("failed_reason", sa.Text(), nullable=True))

    # Update the enum to include 'failed' status
    # PostgreSQL requires recreating the enum type
    op.execute("ALTER TYPE task_status_enum RENAME TO task_status_enum_old")
    op.execute("CREATE TYPE task_status_enum AS ENUM ('pending', 'doing', 'done', 'failed')")
    op.execute("""
        ALTER TABLE tasks 
        ALTER COLUMN status TYPE task_status_enum 
        USING status::text::task_status_enum
    """)
    op.execute("DROP TYPE task_status_enum_old")


def downgrade():
    # Remove failed_reason column
    op.drop_column("tasks", "failed_reason")

    # Revert the enum to exclude 'failed' status
    op.execute("ALTER TYPE task_status_enum RENAME TO task_status_enum_old")
    op.execute("CREATE TYPE task_status_enum AS ENUM ('pending', 'doing', 'done')")
    op.execute("""
        ALTER TABLE tasks 
        ALTER COLUMN status TYPE task_status_enum 
        USING 
            CASE 
                WHEN status::text = 'failed' THEN 'done'::text
                ELSE status::text
            END::task_status_enum
    """)
    op.execute("DROP TYPE task_status_enum_old")
