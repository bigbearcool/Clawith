"""Change AgentRelationship from member_id to user_id

Revision ID: 20260409_agent_rel_user
Revises: 20260409_contacts
Create Date: 2026-04-09

Changes:
1. Add user_id column to agent_relationships
2. Migrate data: user_id = OrgMember.user_id
3. Drop member_id column
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision: str = "20260409_agent_rel_user"
down_revision: Union[str, None] = "20260409_contacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    agent_rel_columns = [c["name"] for c in inspector.get_columns("agent_relationships")]

    # 1. Add user_id column (nullable initially for migration)
    if "user_id" not in agent_rel_columns:
        op.add_column("agent_relationships", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 2. Migrate data: user_id = OrgMember.user_id
    # Execute raw SQL to copy data from org_members.user_id
    op.execute("""
        UPDATE agent_relationships ar
        SET user_id = om.user_id
        FROM org_members om
        WHERE ar.member_id = om.id
    """)

    # 3. Drop the old FK constraint on member_id
    # Find the constraint name
    fk_constraints = inspector.get_foreign_keys("agent_relationships")
    for fk in fk_constraints:
        if "member_id" in fk.get("constrained_columns", []):
            constraint_name = fk.get("name")
            if constraint_name:
                op.drop_constraint(constraint_name, "agent_relationships", type_="foreignkey")
            break

    # 4. Drop member_id column
    if "member_id" in agent_rel_columns:
        op.drop_column("agent_relationships", "member_id")

    # 5. Add FK constraint on user_id
    op.create_foreign_key("fk_agent_relationships_user_id", "agent_relationships", "users", ["user_id"], ["id"])

    # 6. Make user_id NOT NULL
    op.alter_column("agent_relationships", "user_id", nullable=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    agent_rel_columns = [c["name"] for c in inspector.get_columns("agent_relationships")]

    # 1. Drop FK on user_id
    fk_constraints = inspector.get_foreign_keys("agent_relationships")
    for fk in fk_constraints:
        if "user_id" in fk.get("constrained_columns", []):
            constraint_name = fk.get("name")
            if constraint_name:
                op.drop_constraint(constraint_name, "agent_relationships", type_="foreignkey")
            break

    # 2. Add member_id column back
    if "member_id" not in agent_rel_columns:
        op.add_column("agent_relationships", sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True))

    # 3. Make user_id nullable temporarily
    op.alter_column("agent_relationships", "user_id", nullable=True)

    # 4. Add FK on member_id
    op.create_foreign_key(
        "fk_agent_relationships_member_id", "agent_relationships", "org_members", ["member_id"], ["id"]
    )

    # 5. Drop user_id column
    if "user_id" in agent_rel_columns:
        op.drop_column("agent_relationships", "user_id")
