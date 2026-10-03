"""align users with user_name model

Revision ID: 8de830259a14
Revises: 5b1e7c2d9a40
Create Date: 2026-10-03 18:00:00.000000

"""
import secrets
from typing import Sequence, Union

import bcrypt
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8de830259a14'
down_revision: Union[str, Sequence[str], None] = '5b1e7c2d9a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('users', 'handle', new_column_name='user_name')
    op.drop_constraint('users_handle_key', 'users', type_='unique')
    op.create_unique_constraint('users_user_name_key', 'users', ['user_name'])

    op.alter_column('users', 'avatar_url', new_column_name='photo_url')
    op.alter_column('users', 'password_hash', new_column_name='password')
    op.drop_column('users', 'display_name')

    # Password is now required, so the "password or Google" rule is redundant
    op.drop_constraint('ck_users_login_method', 'users', type_='check')

    # Fill NULLs before adding NOT NULL. Users without an email get a unique
    # placeholder; Google-only users get the hash of a random secret that is
    # discarded, so password sign-in can never succeed for them.
    op.execute(
        "UPDATE users SET email = 'user-' || id || '@missing-email.invalid' "
        "WHERE email IS NULL"
    )
    unusable_password = bcrypt.hashpw(
        secrets.token_bytes(32), bcrypt.gensalt()
    ).decode()
    op.get_bind().execute(
        sa.text("UPDATE users SET password = :password WHERE password IS NULL"),
        {"password": unusable_password},
    )
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=False)
    op.alter_column('users', 'password', existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Filled placeholder values are kept; they cannot be told apart from real data
    op.alter_column('users', 'password', existing_type=sa.String(), nullable=True)
    op.alter_column('users', 'email', existing_type=sa.String(), nullable=True)
    op.create_check_constraint(
        'ck_users_login_method', 'users', 'password IS NOT NULL OR google_subject IS NOT NULL'
    )

    op.add_column('users', sa.Column('display_name', sa.String(), nullable=True))
    op.execute('UPDATE users SET display_name = user_name')
    op.alter_column('users', 'display_name', nullable=False)

    op.alter_column('users', 'password', new_column_name='password_hash')
    op.alter_column('users', 'photo_url', new_column_name='avatar_url')

    op.drop_constraint('users_user_name_key', 'users', type_='unique')
    op.create_unique_constraint('users_handle_key', 'users', ['user_name'])
    op.alter_column('users', 'user_name', new_column_name='handle')
