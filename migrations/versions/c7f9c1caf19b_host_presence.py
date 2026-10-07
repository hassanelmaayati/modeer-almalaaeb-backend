"""host presence and admission time

Revision ID: c7f9c1caf19b
Revises: 2d3422f493b4
Create Date: 2026-10-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7f9c1caf19b'
down_revision: Union[str, Sequence[str], None] = '2d3422f493b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add when a player was admitted and since when a started room's host is away."""
    op.add_column('memberships', sa.Column('accepted_at', sa.DateTime(), nullable=True))
    op.add_column('rooms', sa.Column('host_away_since', sa.DateTime(), nullable=True))
    # The real admission time was never stored; the last change to an accepted
    # row is the best estimate for who joined first
    op.execute(
        "UPDATE memberships SET accepted_at = updated_at "
        "WHERE room_id IS NOT NULL AND status = 'accepted' AND accepted_at IS NULL"
    )


def downgrade() -> None:
    """Drop both columns (the admission times are lost)."""
    op.drop_column('rooms', 'host_away_since')
    op.drop_column('memberships', 'accepted_at')
