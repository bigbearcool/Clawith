"""merge_heads

Revision ID: 09ec4c868154
Revises: add_tenant_settings, add_voice_settings
Create Date: 2026-04-09 11:19:17.934051
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '09ec4c868154'
down_revision: Union[str, None] = ('add_tenant_settings', 'add_voice_settings')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
