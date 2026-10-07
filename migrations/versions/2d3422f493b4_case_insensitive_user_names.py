"""case insensitive user names

Revision ID: 2d3422f493b4
Revises: a64cf5d0ee9e
Create Date: 2026-10-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2d3422f493b4'
down_revision: Union[str, Sequence[str], None] = 'a64cf5d0ee9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make user names unique ignoring case. Fails (and rolls back) if two
    existing names differ only by case; rename those users first."""
    op.create_index('uq_users_user_name_lower', 'users', [sa.text('lower(user_name)')], unique=True)


def downgrade() -> None:
    """Allow case-variant names again."""
    op.drop_index('uq_users_user_name_lower', table_name='users')
