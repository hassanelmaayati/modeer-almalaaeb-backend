"""create cups table

Revision ID: 24d753ea5dab
Revises: 8de830259a14
Create Date: 2026-10-03 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '24d753ea5dab'
down_revision: Union[str, Sequence[str], None] = '8de830259a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('cups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organizer_user_id', sa.Integer(), nullable=False),
    sa.Column('sport_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('rules', sa.Text(), nullable=False),
    sa.Column('team_count', sa.Integer(), nullable=False),
    sa.Column('roster_limit', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), server_default='draft', nullable=False),
    sa.Column('registration_closes_at', sa.DateTime(), nullable=True),
    sa.Column('rosters_locked_at', sa.DateTime(), nullable=True),
    sa.Column('entries', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fixtures', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('team_count >= 2', name='ck_cups_team_count'),
    sa.CheckConstraint('roster_limit > 0', name='ck_cups_roster_limit'),
    sa.CheckConstraint(
        "status IN ('draft', 'registration', 'published', 'completed')", name='ck_cups_status'
    ),
    sa.ForeignKeyConstraint(['organizer_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sport_id'], ['sports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cups_id'), 'cups', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_cups_id'), table_name='cups')
    op.drop_table('cups')
