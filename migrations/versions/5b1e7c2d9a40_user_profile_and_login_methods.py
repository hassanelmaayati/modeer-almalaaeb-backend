"""user profile and login methods

Revision ID: 5b1e7c2d9a40
Revises: 44d5a194e0ba
Create Date: 2026-10-03 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b1e7c2d9a40'
down_revision: Union[str, Sequence[str], None] = '44d5a194e0ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('users', 'username', new_column_name='handle')
    op.alter_column('users', 'password', new_column_name='password_hash', nullable=True)
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=True)
    op.drop_constraint('users_username_key', 'users', type_='unique')
    op.create_unique_constraint('users_handle_key', 'users', ['handle'])

    op.add_column('users', sa.Column('display_name', sa.String(), nullable=True))
    op.execute('UPDATE users SET display_name = handle')
    op.alter_column('users', 'display_name', nullable=False)

    op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))
    op.add_column('users', sa.Column('bio', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('google_subject', sa.String(), nullable=True))
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))
    op.create_unique_constraint('users_google_subject_key', 'users', ['google_subject'])

    op.create_check_constraint(
        'ck_users_login_method', 'users', 'password_hash IS NOT NULL OR google_subject IS NOT NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_users_login_method', 'users', type_='check')
    op.drop_constraint('users_google_subject_key', 'users', type_='unique')

    op.drop_column('users', 'token_version')
    op.drop_column('users', 'google_subject')
    op.drop_column('users', 'bio')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'display_name')

    op.drop_constraint('users_handle_key', 'users', type_='unique')
    op.create_unique_constraint('users_username_key', 'users', ['handle'])
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=False)
    op.alter_column('users', 'password_hash', new_column_name='password', nullable=False)
    op.alter_column('users', 'handle', new_column_name='username')
