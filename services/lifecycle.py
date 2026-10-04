import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.room import RoomModel
from serializers.lobby import RoomRemovedEvent
from services.lobby import LobbyHub
from services.lobby_events import LobbyMessage, send_events
from services.room_rules import CUTOFF, as_utc, count_slots_left
from services.changes import change_events
from services.realtime import send_events as send_private_events

logger = logging.getLogger(__name__)

# How often the worker looks for rooms to start, finish or hide from the lobby
LIFECYCLE_INTERVAL_SECONDS = 60


'''
One pass of the worker, using the session it is given. It
  1. starts open rooms whose start time has passed,
  2. finishes started rooms whose end time has passed,
  3. returns room_removed events for public rooms that are now past the cutoff
     or have started, so the lobby stops listing them.
announced holds the room ids already announced, so a room is announced once.
The caller sends the events after this returns, because it commits here.
'''
def run_lifecycle_tick(
    db: Session, announced: set[int], now: datetime | None = None, private_events: list | None = None
) -> list[LobbyMessage]:
    now = now or datetime.now(timezone.utc)
    events: list[LobbyMessage] = []

    # Open rooms that started already or are inside the last 15 minutes before the start
    due = (
        db.query(RoomModel)
        .filter(RoomModel.status == "open", RoomModel.starts_at <= now + CUTOFF)
        .with_for_update().all()
    )
    in_window = set()
    for room in due:
        in_window.add(room.id)

        if as_utc(room.starts_at) <= now:
            room.status = "started"
            room.revision += 1
            if private_events is not None:
                private_events.extend(change_events(db, {"type": "room", "id": room.id},
                    "room.started", "A room you joined has started", room.host_id))

        # Only public rooms were ever in the lobby, and a room is announced once.
        # A room with no free place was already removed when it filled up.
        if room.visibility != "public" or room.id in announced:
            continue
        announced.add(room.id)
        if count_slots_left(db, room) > 0:
            reason = "started" if room.status == "started" else "past_cutoff"
            events.append((room.district, RoomRemovedEvent(room_id=room.id, reason=reason)))

    # Forget rooms that left the window (they started), so the set stays small
    announced.intersection_update(in_window)

    # Make the status changes above visible to the next query
    db.flush()

    ended = (
        db.query(RoomModel)
        .filter(RoomModel.status == "started", RoomModel.ends_at <= now)
        .with_for_update().all()
    )
    for room in ended:
        room.status = "completed"
        room.revision += 1
        if private_events is not None:
            private_events.extend(change_events(db, {"type": "room", "id": room.id},
                "room.completed", "A room you joined has finished", room.host_id))

    db.commit()
    return events


# Runs one pass in a worker thread (the database calls block) with its own session
def _tick_in_thread(session_factory, announced: set[int]):
    db = session_factory()
    try:
        # Work on a copy, so a failed commit does not mark rooms as announced
        # when their events were never sent
        seen = set(announced)
        private_events = []
        events = run_lifecycle_tick(db, seen, private_events=private_events)
        announced.clear()
        announced.update(seen)
        return events, private_events
    finally:
        db.close()


'''
Runs for as long as the app runs. It does a pass straight away, which catches up
after downtime, and then one every interval. A failed pass is logged and the
next one runs as usual.
'''
async def lifecycle_loop(
    interval: float = LIFECYCLE_INTERVAL_SECONDS,
    session_factory=None,
    hub: LobbyHub | None = None,
) -> None:
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal

    announced: set[int] = set()
    while True:
        try:
            events, private_events = await asyncio.to_thread(_tick_in_thread, session_factory, announced)
            await send_events(events, hub)
            await send_private_events(private_events)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Lifecycle worker pass failed")
        await asyncio.sleep(interval)
