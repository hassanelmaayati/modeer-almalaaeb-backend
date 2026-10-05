"""initial current schema

Revision ID: 1243039bc68a
Revises:
Create Date: 2026-10-05 09:53:16.384568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1243039bc68a'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public')
    op.create_table('sports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('formats', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sports_id'), 'sports', ['id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_name', sa.String(), nullable=False),
    sa.Column('photo_url', sa.String(), nullable=True),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('district', sa.String(), nullable=True),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('password', sa.String(), nullable=False),
    sa.Column('google_subject', sa.String(), nullable=True),
    sa.Column('token_version', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("district IS NULL OR district IN ('capital', 'muharraq', 'northern', 'southern')", name='ck_users_district'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('google_subject'),
    sa.UniqueConstraint('user_name')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
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
    sa.Column('entries', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('fixtures', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("status IN ('draft', 'registration', 'published', 'completed')", name='ck_cups_status'),
    sa.CheckConstraint('roster_limit > 0', name='ck_cups_roster_limit'),
    sa.CheckConstraint('team_count >= 2', name='ck_cups_team_count'),
    sa.ForeignKeyConstraint(['organizer_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sport_id'], ['sports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_cups_id'), 'cups', ['id'], unique=False)
    op.create_table('groups',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('photo_url', sa.String(), nullable=True),
    sa.Column('sports_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sports_id'], ['sports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_groups_id'), 'groups', ['id'], unique=False)
    op.create_table('notifications',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('target', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint('length(trim(kind)) > 0', name='ck_notifications_kind_not_blank'),
    sa.CheckConstraint('length(trim(text)) > 0', name='ck_notifications_text_not_blank'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_id'), 'notifications', ['id'], unique=False)
    op.create_index('ix_notifications_user_id_id', 'notifications', ['user_id', 'id'], unique=False)
    op.create_index('ix_notifications_user_unread', 'notifications', ['user_id', 'read_at'], unique=False)
    op.create_table('rooms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('host_id', sa.Integer(), nullable=False),
    sa.Column('sport_id', sa.Integer(), nullable=False),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('difficulty', sa.String(), server_default='beginners', nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('capacity', sa.Integer(), nullable=False),
    sa.Column('slot_layout', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(), server_default='open', nullable=False),
    sa.Column('visibility', sa.String(), server_default='public', nullable=False),
    sa.Column('admission_policy', sa.String(), server_default='approval', nullable=False),
    sa.Column('cancellation_reason', sa.Text(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('district', sa.String(), nullable=False),
    sa.Column('area', sa.String(), nullable=False),
    sa.Column('venue_point', Geography(geometry_type='POINT', srid=4326, dimension=2, spatial_index=False, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('venue_notes', sa.Text(), nullable=True),
    sa.Column('distance_km', sa.Float(), nullable=True),
    sa.Column('pace_notes', sa.String(), nullable=True),
    sa.Column('route_notes', sa.Text(), nullable=True),
    sa.Column('host_generation', sa.Integer(), server_default='0', nullable=False),
    sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("admission_policy IN ('approval', 'open')", name='ck_rooms_admission_policy'),
    sa.CheckConstraint("difficulty IN ('beginners', 'medium', 'advanced')", name='ck_rooms_difficulty'),
    sa.CheckConstraint("district IN ('capital', 'muharraq', 'northern', 'southern')", name='ck_rooms_district'),
    sa.CheckConstraint("status IN ('open', 'started', 'completed', 'cancelled')", name='ck_rooms_status'),
    sa.CheckConstraint("visibility != 'group' OR group_id IS NOT NULL", name='ck_rooms_group_visibility_needs_group'),
    sa.CheckConstraint("visibility IN ('public', 'private', 'group')", name='ck_rooms_visibility'),
    sa.CheckConstraint('capacity > 0', name='ck_rooms_capacity_positive'),
    sa.CheckConstraint('ends_at > starts_at', name='ck_rooms_end_after_start'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
    sa.ForeignKeyConstraint(['host_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['sport_id'], ['sports.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_rooms_district_status_starts_at', 'rooms', ['district', 'status', 'starts_at'], unique=False)
    op.create_index('ix_rooms_host_id_starts_at', 'rooms', ['host_id', 'starts_at'], unique=False)
    op.create_index(op.f('ix_rooms_id'), 'rooms', ['id'], unique=False)
    op.create_index('ix_rooms_venue_point', 'rooms', ['venue_point'], unique=False, postgresql_using='gist')
    op.create_table('memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('other_user_id', sa.Integer(), nullable=True),
    sa.Column('room_id', sa.Integer(), nullable=True),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('cup_id', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('position', sa.String(), nullable=True),
    sa.Column('attendance', sa.String(), nullable=True),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('requested', sa.Boolean(), nullable=True),
    sa.Column('accepted', sa.Boolean(), nullable=True),
    sa.Column('user_blocked_other', sa.String(), nullable=True),
    sa.Column('other_blocked_user', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['cup_id'], ['cups.id'], ),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
    sa.ForeignKeyConstraint(['other_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'cup_id', name='uq_memberships_user_cup'),
    sa.UniqueConstraint('user_id', 'room_id', name='uq_memberships_user_room')
    )
    op.create_index(op.f('ix_memberships_id'), 'memberships', ['id'], unique=False)
    op.create_index('uq_memberships_friend_pair', 'memberships', [sa.literal_column('(CASE WHEN (user_id < other_user_id) THEN user_id ELSE other_user_id END)'), sa.literal_column('(CASE WHEN (user_id < other_user_id) THEN other_user_id ELSE user_id END)')], unique=True, postgresql_where=sa.text('other_user_id IS NOT NULL'), sqlite_where=sa.text('other_user_id IS NOT NULL'))
    op.create_index('uq_memberships_room_position', 'memberships', ['room_id', 'position'], unique=True, postgresql_where=sa.text("status = 'accepted' AND position IS NOT NULL"), sqlite_where=sa.text("status = 'accepted' AND position IS NOT NULL"))
    op.create_index('uq_memberships_user_group', 'memberships', ['user_id', 'group_id'], unique=True, postgresql_where=sa.text('group_id IS NOT NULL AND cup_id IS NULL'), sqlite_where=sa.text('group_id IS NOT NULL AND cup_id IS NULL'))
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sender_id', sa.Integer(), nullable=True),
    sa.Column('recipient_id', sa.Integer(), nullable=True),
    sa.Column('room_id', sa.Integer(), nullable=True),
    sa.Column('group_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('client_request_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.CheckConstraint("(type = 'room' AND room_id IS NOT NULL AND sender_id IS NOT NULL) OR (type = 'direct' AND recipient_id IS NOT NULL AND sender_id IS NOT NULL) OR (type = 'group' AND group_id IS NOT NULL AND sender_id IS NOT NULL) OR (type = 'system' AND room_id IS NOT NULL AND sender_id IS NULL)", name='ck_messages_type_matches_target'),
    sa.CheckConstraint("type IN ('room', 'direct', 'group', 'system')", name='ck_messages_type'),
    sa.CheckConstraint('(room_id IS NOT NULL AND recipient_id IS NULL AND group_id IS NULL) OR (room_id IS NULL AND recipient_id IS NOT NULL AND group_id IS NULL) OR (room_id IS NULL AND recipient_id IS NULL AND group_id IS NOT NULL)', name='ck_messages_exactly_one_target'),
    sa.CheckConstraint('length(trim(body)) > 0', name='ck_messages_body_not_blank'),
    sa.CheckConstraint('recipient_id IS NULL OR sender_id != recipient_id', name='ck_messages_no_self_message'),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name='fk_messages_group_id_groups'),
    sa.ForeignKeyConstraint(['recipient_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sender_id', 'client_request_id', name='uq_messages_sender_request')
    )
    op.create_index('ix_messages_group_created', 'messages', ['group_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_messages_id'), 'messages', ['id'], unique=False)
    op.create_index('ix_messages_recipient_created', 'messages', ['recipient_id', 'created_at'], unique=False)
    op.create_index('ix_messages_room_created', 'messages', ['room_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Drop application tables; retain the shared PostGIS extension."""
    op.drop_index('ix_messages_room_created', table_name='messages')
    op.drop_index('ix_messages_recipient_created', table_name='messages')
    op.drop_index(op.f('ix_messages_id'), table_name='messages')
    op.drop_index('ix_messages_group_created', table_name='messages')
    op.drop_table('messages')
    op.drop_index('uq_memberships_user_group', table_name='memberships', postgresql_where=sa.text('group_id IS NOT NULL AND cup_id IS NULL'), sqlite_where=sa.text('group_id IS NOT NULL AND cup_id IS NULL'))
    op.drop_index('uq_memberships_room_position', table_name='memberships', postgresql_where=sa.text("status = 'accepted' AND position IS NOT NULL"), sqlite_where=sa.text("status = 'accepted' AND position IS NOT NULL"))
    op.drop_index('uq_memberships_friend_pair', table_name='memberships', postgresql_where=sa.text('other_user_id IS NOT NULL'), sqlite_where=sa.text('other_user_id IS NOT NULL'))
    op.drop_index(op.f('ix_memberships_id'), table_name='memberships')
    op.drop_table('memberships')
    op.drop_index('ix_rooms_venue_point', table_name='rooms', postgresql_using='gist')
    op.drop_index(op.f('ix_rooms_id'), table_name='rooms')
    op.drop_index('ix_rooms_host_id_starts_at', table_name='rooms')
    op.drop_index('ix_rooms_district_status_starts_at', table_name='rooms')
    op.drop_table('rooms')
    op.drop_index('ix_notifications_user_unread', table_name='notifications')
    op.drop_index('ix_notifications_user_id_id', table_name='notifications')
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_groups_id'), table_name='groups')
    op.drop_table('groups')
    op.drop_index(op.f('ix_cups_id'), table_name='cups')
    op.drop_table('cups')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_sports_id'), table_name='sports')
    op.drop_table('sports')
