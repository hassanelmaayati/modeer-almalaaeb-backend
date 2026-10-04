import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.membership import MembershipModel
from models.room import RoomModel
from services.lobby import LobbyHub
from services.lobby_events import (
    events_for_change,
    lobby_state,
    publish_room_event,
)
from services.room_rules import count_slots_left


# Records what would be sent instead of using sockets
class RecordingHub(LobbyHub):
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def connect(self, socket): ...
    async def subscribe(self, socket, district): ...
    async def unsubscribe(self, socket): ...
    async def disconnect(self, socket): ...

    async def broadcast(self, district, event):
        if self.fail:
            raise RuntimeError("hub is down")
        self.sent.append((district, event))


def add_room(db: Session, **overrides) -> RoomModel:
    now = datetime.now(timezone.utc)
    values = dict(
        host_id=1,
        sport_id=1,
        title="Lobby room",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=1),
        capacity=4,
        district="capital",
        public_area="Manama",
        venue_details="Secret court 9",
    )
    values.update(overrides)
    room = RoomModel(**values)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def add_member(db: Session, room: RoomModel, user_id: int, status="accepted"):
    member = MembershipModel(user_id=user_id, room_id=room.id, status=status)
    db.add(member)
    db.commit()
    return member


def publish(db, room, before=None):
    hub = RecordingHub()
    asyncio.run(publish_room_event(db, room, before, hub=hub))
    return hub.sent


def summary(sent):
    # [(district, event type)] is enough for most checks
    return [(district, event.type) for district, event in sent]


# ---------- slots left ----------


def test_host_takes_one_slot(test_db: Session):
    room = add_room(test_db, capacity=4)
    assert count_slots_left(test_db, room) == 3


def test_accepted_players_take_slots_but_pending_ones_do_not(test_db: Session):
    room = add_room(test_db, capacity=4)
    add_member(test_db, room, 2, "accepted")
    add_member(test_db, room, 3, "pending")
    add_member(test_db, room, 4, "declined")
    assert count_slots_left(test_db, room) == 2


def test_host_with_a_membership_row_counts_once(test_db: Session):
    room = add_room(test_db, capacity=4)
    add_member(test_db, room, 1, "accepted")  # the host
    assert count_slots_left(test_db, room) == 3


def test_slots_left_never_negative(test_db: Session):
    room = add_room(test_db, capacity=1)
    add_member(test_db, room, 2, "accepted")
    assert count_slots_left(test_db, room) == 0


# ---------- new rooms ----------


def test_new_public_room_is_published_on_its_district(test_db: Session):
    room = add_room(test_db, district="muharraq", capacity=6)
    sent = publish(test_db, room, before=None)

    assert summary(sent) == [("muharraq", "room_created")]
    payload = sent[0][1].room
    assert payload.id == room.id
    assert payload.slots_left == 5
    assert payload.sport_name


def test_published_payload_has_public_fields_only(test_db: Session):
    room = add_room(test_db)
    sent = publish(test_db, room)

    text = sent[0][1].model_dump_json()
    assert "Secret court 9" not in text
    assert set(json.loads(text)["room"]) == {
        "id", "title", "sport_id", "sport_name", "district", "public_area",
        "starts_at", "capacity", "slots_left", "difficulty", "revision",
    }


def test_private_and_group_rooms_are_never_published(test_db: Session):
    private = add_room(test_db, visibility="private")
    group = add_room(test_db, visibility="group", group_id=1)

    assert publish(test_db, private) == []
    assert publish(test_db, group) == []


def test_unlisted_rooms_are_not_published(test_db: Session):
    now = datetime.now(timezone.utc)
    cancelled = add_room(test_db, status="cancelled")
    started = add_room(test_db, status="started")
    past_cutoff = add_room(
        test_db, starts_at=now + timedelta(minutes=10), ends_at=now + timedelta(hours=1)
    )
    full = add_room(test_db, capacity=1)

    for room in (cancelled, started, past_cutoff, full):
        assert publish(test_db, room) == [], room.id


# ---------- changes to a shown room ----------


def test_edit_in_same_district_sends_room_updated(test_db: Session):
    room = add_room(test_db)
    before = lobby_state(test_db, room)

    room.title = "New title"
    room.revision += 1
    test_db.commit()

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_updated")]
    assert sent[0][1].room.title == "New title"
    assert sent[0][1].room.revision == 1


def test_joining_updates_slots_left(test_db: Session):
    room = add_room(test_db, capacity=4)
    before = lobby_state(test_db, room)
    add_member(test_db, room, 2, "accepted")

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_updated")]
    assert sent[0][1].room.slots_left == 2


def test_changing_district_moves_the_room(test_db: Session):
    room = add_room(test_db, district="capital")
    before = lobby_state(test_db, room)

    room.district = "northern"
    test_db.commit()

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed"), ("northern", "room_created")]
    assert sent[0][1].reason == "moved"


def test_cancelled_room_is_removed(test_db: Session):
    room = add_room(test_db)
    before = lobby_state(test_db, room)
    room.status = "cancelled"
    test_db.commit()

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed")]
    assert sent[0][1].reason == "cancelled"


def test_started_room_is_removed(test_db: Session):
    room = add_room(test_db)
    before = lobby_state(test_db, room)
    room.status = "started"
    test_db.commit()

    assert publish(test_db, room, before)[0][1].reason == "started"


def test_room_that_crosses_the_cutoff_is_removed(test_db: Session):
    room = add_room(test_db)
    before = lobby_state(test_db, room)
    room.starts_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    test_db.commit()

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed")]
    assert sent[0][1].reason == "past_cutoff"


def test_room_made_private_is_removed_and_then_stays_silent(test_db: Session):
    room = add_room(test_db)
    before = lobby_state(test_db, room)
    room.visibility = "private"
    test_db.commit()

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed")]
    assert sent[0][1].reason == "not_public"

    # Later edits to the private room say nothing at all
    after_private = lobby_state(test_db, room)
    room.title = "Secret plans"
    test_db.commit()
    assert publish(test_db, room, after_private) == []


def test_room_made_public_appears(test_db: Session):
    room = add_room(test_db, visibility="private")
    before = lobby_state(test_db, room)
    room.visibility = "public"
    test_db.commit()

    assert summary(publish(test_db, room, before)) == [("capital", "room_created")]


def test_filling_up_removes_and_a_free_place_brings_it_back(test_db: Session):
    room = add_room(test_db, capacity=2)
    before = lobby_state(test_db, room)
    member = add_member(test_db, room, 2, "accepted")

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed")]
    assert sent[0][1].reason == "full"

    before = lobby_state(test_db, room)
    member.status = "left"
    test_db.commit()
    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_created")]
    assert sent[0][1].room.slots_left == 1


def test_room_that_moves_district_while_becoming_full_is_removed_from_the_old_one(
    test_db: Session,
):
    room = add_room(test_db, capacity=2, district="capital")
    before = lobby_state(test_db, room)
    room.district = "southern"
    add_member(test_db, room, 2, "accepted")

    sent = publish(test_db, room, before)
    assert summary(sent) == [("capital", "room_removed")]
    assert sent[0][1].reason == "full"


# ---------- safety ----------


def test_nothing_is_decided_for_a_room_that_was_never_shown(test_db: Session):
    room = add_room(test_db, visibility="private")
    before = lobby_state(test_db, room)
    assert events_for_change(test_db, room, before) == []


def test_publish_never_raises(test_db: Session):
    room = add_room(test_db)
    asyncio.run(publish_room_event(test_db, room, None, hub=RecordingHub(fail=True)))
