"""Complete invitation policy matrices and deterministic scheduling boundaries."""
from datetime import datetime, timedelta, timezone
from itertools import product
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from models.membership import MembershipModel
from models.room import RoomModel
from models.notification import NotificationModel
from services.memberships import invitation_transition
from services import lifecycle
from tests.lib import api

STATES = ('pending', 'accepted', 'declined', 'left', 'removed')


@pytest.mark.parametrize('old,new,actor', list(product(STATES, STATES, ('invitee', 'owner', 'outsider'))))
def test_group_and_cup_invitation_transition_policy_is_complete(old, new, actor):
    row = SimpleNamespace(status=old, accepted=old == 'accepted')
    permissions = {
        ('invitee', 'pending'): {'accepted', 'declined', 'left'},
        ('invitee', 'accepted'): {'left'},
        ('owner', 'pending'): {'removed'},
        ('owner', 'accepted'): {'removed'},
    }
    if new in permissions.get((actor, old), set()):
        invitation_transition(row, new, is_self=actor == 'invitee', is_owner=actor == 'owner')
        assert row.status == new and row.accepted == (new == 'accepted')
    else:
        with pytest.raises(HTTPException) as denied:
            invitation_transition(row, new, is_self=actor == 'invitee', is_owner=actor == 'owner')
        assert denied.value.status_code == 403
        assert row.status == old and row.accepted == (old == 'accepted')


@pytest.mark.parametrize('requested,actor,new,status', [
    (True, 'host', 'accepted', 200), (True, 'host', 'declined', 200),
    (True, 'player', 'accepted', 403), (True, 'player', 'declined', 403),
    (False, 'player', 'accepted', 200), (False, 'player', 'declined', 200),
    (False, 'host', 'accepted', 403), (False, 'host', 'declined', 403),
    (True, 'host', 'removed', 200), (False, 'host', 'removed', 200),
    (True, 'player', 'left', 200), (False, 'player', 'left', 200),
    (True, 'outsider', 'accepted', 403), (False, 'outsider', 'removed', 403),
])
def test_room_request_vs_invitation_actor_policy_persists_only_allowed_transitions(client, factory, db, requested, actor, new, status):
    host, player, outsider = factory.user(), factory.user(), factory.user()
    room = factory.room(host)
    row = factory.member(player, room=room, status='pending', requested=requested)
    acting = {'host': host, 'player': player, 'outsider': outsider}[actor]
    api(client, 'PATCH', f"/rooms/{room['id']}/members/{player['id']}", user=acting, body={'status': new}, expected=status)
    with db() as session:
        member = session.get(MembershipModel, row['id'])
        stored_room = session.get(RoomModel, room['id'])
        assert member.status == (new if status == 200 else 'pending')
        assert member.accepted == (status == 200 and new == 'accepted')
        assert stored_room.revision == (1 if status == 200 else 0)
        if status != 200:
            assert session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('old,actor,new,expected', [
    ('pending', 'requester', 'accepted', 403), ('pending', 'requester', 'declined', 403),
    ('pending', 'requester', 'left', 200), ('pending', 'target', 'accepted', 200),
    ('pending', 'target', 'declined', 200), ('pending', 'target', 'left', 403),
    ('accepted', 'requester', 'left', 200), ('accepted', 'target', 'left', 200),
    ('accepted', 'requester', 'declined', 403), ('declined', 'target', 'left', 403),
    ('left', 'requester', 'accepted', 403), ('removed', 'target', 'declined', 403),
])
def test_friendship_transition_policy_and_rollback(client, factory, db, old, actor, new, expected):
    requester, target = factory.user(), factory.user()
    row = factory.friend(requester, target, status=old)
    acting, other = (requester, target) if actor == 'requester' else (target, requester)
    api(client, 'PATCH', f"/friends/{other['id']}", user=acting, body={'status': new}, expected=expected)
    with db() as session:
        stored = session.get(MembershipModel, row['id'])
        assert stored.status == (new if expected == 200 else old)
        assert stored.accepted == ((new if expected == 200 else old) == 'accepted')
        if expected != 200:
            assert session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('offset,valid', [(3599, False), (3600, True), (3601, True), (1209600, True), (1209601, False)])
def test_room_lead_time_exact_boundaries_use_a_frozen_clock(monkeypatch, offset, valid):
    import serializers.room as schemas
    frozen = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)
    monkeypatch.setattr(schemas, 'datetime', FixedDateTime)
    payload = dict(sport_id=1, title='Boundary room', capacity=4, starts_at=frozen + timedelta(seconds=offset),
                   ends_at=frozen + timedelta(seconds=offset, hours=1), district='capital', area='Manama')
    if valid:
        assert schemas.CreateRoomSchema(**payload).starts_at == payload['starts_at']
    else:
        with pytest.raises(ValidationError):
            schemas.CreateRoomSchema(**payload)


@pytest.mark.parametrize('offset,expected,revision', [(-1, 'open', 0), (0, 'started', 1), (3599, 'started', 1), (3600, 'completed', 2)])
def test_lifecycle_exact_start_and_end_boundaries_are_idempotent(factory, db, offset, expected, revision):
    now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    host, player = factory.user(), factory.user()
    room = factory.room(host, starts_at=now, ends_at=now + timedelta(hours=1))
    factory.member(player, room=room)
    tick_at = now + timedelta(seconds=offset)
    seen = set()
    for _ in range(2):
        with db() as session:
            lifecycle.run_lifecycle_tick(session, seen, now=tick_at, private_events=[])
    with db() as session:
        stored = session.get(RoomModel, room['id'])
        assert stored.status == expected and stored.revision == revision
        notices = session.query(NotificationModel).filter_by(user_id=player['id']).all()
        assert len(notices) == revision


def test_room_timezone_offsets_normalize_and_naive_inputs_are_rejected():
    from serializers.room import CreateRoomSchema
    from tests.lib import room_body
    start = datetime.now(timezone.utc) + timedelta(days=2)
    bahrain = timezone(timedelta(hours=3))
    parsed = CreateRoomSchema(**room_body(1, starts_at=start.astimezone(bahrain), ends_at=(start + timedelta(hours=1)).astimezone(bahrain)))
    assert parsed.starts_at == start and parsed.starts_at.tzinfo == timezone.utc
    with pytest.raises(ValidationError):
        CreateRoomSchema(**room_body(1, starts_at=start.replace(tzinfo=None)))


@pytest.mark.parametrize('distance', [float('inf'), float('nan'), -1, 0])
def test_room_distance_must_be_finite_and_positive(distance):
    from serializers.room import CreateRoomSchema, UpdateRoomSchema
    from tests.lib import room_body
    with pytest.raises(ValidationError):
        CreateRoomSchema(**room_body(1, distance_km=distance))
    with pytest.raises(ValidationError):
        UpdateRoomSchema(revision=0, distance_km=distance)
