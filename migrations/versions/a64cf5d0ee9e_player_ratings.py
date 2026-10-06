"""player ratings

Revision ID: a64cf5d0ee9e
Revises: 1243039bc68a
Create Date: 2026-10-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a64cf5d0ee9e'
down_revision: Union[str, Sequence[str], None] = '1243039bc68a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the player_ratings table."""
    op.create_table('player_ratings',
    sa.Column('rater_id', sa.Integer(), nullable=False),
    sa.Column('ratee_id', sa.Integer(), nullable=False),
    sa.Column('room_id', sa.Integer(), nullable=False),
    sa.Column('stars', sa.Integer(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('rater_id <> ratee_id', name='ck_player_ratings_not_self'),
    sa.CheckConstraint('stars BETWEEN 1 AND 5', name='ck_player_ratings_stars'),
    sa.ForeignKeyConstraint(['ratee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['rater_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('rater_id', 'ratee_id', 'room_id', name='uq_player_ratings_rater_ratee_room')
    )
    op.create_index(op.f('ix_player_ratings_id'), 'player_ratings', ['id'], unique=False)
    op.create_index('ix_player_ratings_ratee_id', 'player_ratings', ['ratee_id'], unique=False)


def downgrade() -> None:
    """Drop the player_ratings table and every rating in it."""
    op.drop_index('ix_player_ratings_ratee_id', table_name='player_ratings')
    op.drop_index(op.f('ix_player_ratings_id'), table_name='player_ratings')
    op.drop_table('player_ratings')
