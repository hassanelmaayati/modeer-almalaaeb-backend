"""paging indexes and message edits

Revision ID: 7391d0732666
Revises: c7f9c1caf19b
Create Date: 2026-10-07 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7391d0732666'
down_revision: Union[str, Sequence[str], None] = 'c7f9c1caf19b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Index the lookups that lists and counts run on, and add message edit/delete times."""
    op.create_index('ix_memberships_room_id_status', 'memberships', ['room_id', 'status'], unique=False)
    op.create_index('ix_memberships_group_id_status', 'memberships', ['group_id', 'status'], unique=False)
    op.create_index('ix_memberships_cup_id_status', 'memberships', ['cup_id', 'status'], unique=False)
    op.create_index('ix_memberships_other_user_id', 'memberships', ['other_user_id'], unique=False,
                    postgresql_where=sa.text('other_user_id IS NOT NULL'))
    op.create_index('ix_cups_status_created_at', 'cups', ['status', 'created_at'], unique=False)
    op.create_index('ix_cups_organizer_user_id', 'cups', ['organizer_user_id'], unique=False)
    op.create_index('ix_rooms_group_id', 'rooms', ['group_id'], unique=False)
    op.add_column('messages', sa.Column('edited_at', sa.DateTime(), nullable=True))
    op.add_column('messages', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the columns (edit and delete times are lost) and the indexes."""
    op.drop_column('messages', 'deleted_at')
    op.drop_column('messages', 'edited_at')
    op.drop_index('ix_rooms_group_id', table_name='rooms')
    op.drop_index('ix_cups_organizer_user_id', table_name='cups')
    op.drop_index('ix_cups_status_created_at', table_name='cups')
    op.drop_index('ix_memberships_other_user_id', table_name='memberships',
                  postgresql_where=sa.text('other_user_id IS NOT NULL'))
    op.drop_index('ix_memberships_cup_id_status', table_name='memberships')
    op.drop_index('ix_memberships_group_id_status', table_name='memberships')
    op.drop_index('ix_memberships_room_id_status', table_name='memberships')
