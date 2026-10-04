import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.membership import MembershipModel
from models.room import RoomModel
from services.lifecycle import lifecycle_loop, run_lifecycle_tick
from tests.conftest import TestingSessionLocal
from tests.test_lobby_hooks import RecordingHub


def minutes(n):
    return datetime.now(timezone.utc) + timedelta(minutes=n)


def add_room(db: Session, starts_in, lasts=60, **overrides) -> RoomModel:
    start = minutes(starts_in)
    values = dict(
        host_id=1,
        sport_id=4,
        title="Lifecycle room",
        starts_at=start,
        ends_at=start + timedelta(minutes=lasts),
        capacity=4,
        district="capital",
        area="Manama",
    )
    values.update(overrides)
    room = RoomModel(**values)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


def tick(db: Session, announced: set | None = None):
    announced = set() if announced is None else announced
    events = run_lifecycle_tick(db, announced)
    db.expire_all()
    return events


def removed(events):
    return {event.room_id: (district, event.reason) for district, event in events}


# ---------- hiding rooms from the lobby ----------


def test_room_inside_the_cutoff_window_is_removed_but_stays_open(test_db: Session):
    room = add_room(test_db, starts_in=10)
    events = tick(test_db)

    assert removed(events)[room.id] == ("capital", "past_cutoff")
    assert room.status == "open"


def test_room_that_has_started_is_marked_started_and_removed(test_db: Session):
    room = add_room(test_db, starts_in=-1)
    events = tick(test_db)

    assert room.status == "started"
    assert removed(events)[room.id] == ("capital", "started")
    assert room.revision == 1


def test_a_room_is_announced_only_once(test_db: Session):
    room = add_room(test_db, starts_in=10)
    announced: set = set()

    assert room.id in removed(tick(test_db, announced))
    assert room.id not in removed(tick(test_db, announced))


def test_room_announced_at_cutoff_is_not_announced_again_when_it_starts(test_db: Session):
    room = add_room(test_db, starts_in=10)
    announced: set = set()
    tick(test_db, announced)

    room.starts_at = minutes(-1)  # time passes
    test_db.commit()
    events = tick(test_db, announced)

    assert room.status == "started"
    assert room.id not in removed(events)


def test_announced_set_is_trimmed_once_a_room_has_started(test_db: Session):
    room = add_room(test_db, starts_in=-1)
    announced: set = set()
    tick(test_db, announced)  # starts the room and announces it
    tick(test_db, announced)  # the room is gone from the window
    assert room.id not in announced


def test_private_and_group_rooms_are_never_announced_but_still_start(test_db: Session):
    private = add_room(test_db, starts_in=-1, visibility="private")
    group = add_room(test_db, starts_in=-1, visibility="group", group_id=1)
    events = tick(test_db)

    assert private.id not in removed(events)
    assert group.id not in removed(events)
    assert private.status == "started"
    assert group.status == "started"


def test_full_room_is_not_announced_again(test_db: Session):
    room = add_room(test_db, starts_in=-1, capacity=2)
    test_db.add(MembershipModel(user_id=2, room_id=room.id, status="accepted"))
    test_db.commit()

    events = tick(test_db)
    assert room.id not in removed(events)  # it left the lobby when it filled up
    assert room.status == "started"


def test_room_with_pending_requests_only_is_still_announced(test_db: Session):
    room = add_room(test_db, starts_in=5, capacity=2)
    test_db.add(MembershipModel(user_id=2, room_id=room.id, status="pending"))
    test_db.commit()

    assert room.id in removed(tick(test_db))


def test_rooms_far_from_the_start_and_cancelled_rooms_are_left_alone(test_db: Session):
    later = add_room(test_db, starts_in=60 * 24)
    cancelled = add_room(test_db, starts_in=-5, status="cancelled")
    events = tick(test_db)

    assert later.id not in removed(events)
    assert cancelled.id not in removed(events)
    assert later.status == "open"
    assert cancelled.status == "cancelled"


# ---------- finishing rooms ----------


def test_started_room_is_completed_after_it_ends(test_db: Session):
    room = add_room(test_db, starts_in=-90, lasts=60, status="started")
    tick(test_db)
    assert room.status == "completed"


def test_started_room_that_has_not_ended_stays_started(test_db: Session):
    room = add_room(test_db, starts_in=-10, lasts=60, status="started")
    tick(test_db)
    assert room.status == "started"


def test_room_missed_by_downtime_goes_straight_to_completed(test_db: Session):
    room = add_room(test_db, starts_in=-180, lasts=60)  # never started, already over
    tick(test_db)
    assert room.status == "completed"


# ---------- the loop ----------


def test_loop_runs_a_pass_at_once_and_sends_the_events(test_db: Session):
    room = add_room(test_db, starts_in=5)
    hub = RecordingHub()

    async def scenario():
        task = asyncio.create_task(
            lifecycle_loop(interval=0.05, session_factory=TestingSessionLocal, hub=hub)
        )
        await asyncio.sleep(0.4)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    sent = [(d, e.type, e.room_id) for d, e in hub.sent if e.room_id == room.id]
    assert sent == [("capital", "room_removed", room.id)]  # once, despite many passes


def test_loop_survives_a_failing_pass(test_db: Session):
    calls = []

    def broken_factory():
        calls.append(1)
        raise RuntimeError("database is down")

    async def scenario():
        task = asyncio.create_task(
            lifecycle_loop(interval=0.02, session_factory=broken_factory, hub=RecordingHub())
        )
        await asyncio.sleep(0.2)
        assert not task.done()  # still running
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert len(calls) >= 2


# ---------- the app starts and stops the worker ----------


def test_lifespan_starts_the_worker_and_cancels_it_on_shutdown(monkeypatch):
    import main
    from starlette.testclient import TestClient

    log = []

    async def fake_worker():
        log.append("started")
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            log.append("cancelled")
            raise

    monkeypatch.setattr(main, "lifecycle_loop", fake_worker)
    monkeypatch.setattr(main, "LIFECYCLE_WORKER_ENABLED", True)
    with TestClient(main.app):
        pass
    assert log == ["started", "cancelled"]


def test_lifespan_does_not_start_the_worker_when_switched_off(monkeypatch):
    import main
    from starlette.testclient import TestClient

    log = []

    async def fake_worker():
        log.append("started")

    monkeypatch.setattr(main, "lifecycle_loop", fake_worker)
    monkeypatch.setattr(main, "LIFECYCLE_WORKER_ENABLED", False)
    with TestClient(main.app):
        pass
    assert log == []
