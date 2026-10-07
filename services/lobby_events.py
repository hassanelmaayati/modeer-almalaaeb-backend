import logging
from dataclasses import dataclass

from fastapi import BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.room import RoomModel
from serializers.lobby import (
    LobbyRoomSchema,
    RemovedReason,
    RoomCreatedEvent,
    RoomRemovedEvent,
    RoomUpdatedEvent,
)
from services.lobby import LobbyHub, lobby_hub
from services.room_rules import count_slots_left, is_listable, is_past_cutoff

logger = logging.getLogger(__name__)

# A district channel and the event to send on it
LobbyMessage = tuple[str, BaseModel]


# What a room looked like to the lobby at one moment.
# room is what the lobby shows, and it is None when the room is not shown.
@dataclass(frozen=True)
class LobbyState:
    district: str
    visible: bool
    room: LobbyRoomSchema | None = None


'''
A room is shown in the lobby only if the REST list would show it (public, open,
before the cutoff) and it still has a free place. Private and group rooms are
never visible, so nothing about them can reach the lobby.
'''
def is_visible_in_lobby(db: Session, room: RoomModel) -> bool:
    return is_listable(room) and count_slots_left(db, room) > 0


# Call this BEFORE changing the room, then hand it to the publish functions afterwards
def lobby_state(db: Session, room: RoomModel) -> LobbyState:
    if not is_visible_in_lobby(db, room):
        return LobbyState(district=room.district, visible=False)
    return LobbyState(district=room.district, visible=True, room=to_lobby_room(db, room))


def to_lobby_room(db: Session, room: RoomModel) -> LobbyRoomSchema:
    # Public fields only, built one by one so a new column can never leak by accident
    return LobbyRoomSchema(
        id=room.id,
        title=room.title,
        sport_id=room.sport_id,
        sport_name=room.sport.name,
        district=room.district,
        area=room.area,
        starts_at=room.starts_at,
        capacity=room.capacity,
        slots_left=count_slots_left(db, room),
        difficulty=room.difficulty,
        revision=room.revision,
    )


# Why a room that was shown is no longer shown
def removal_reason(room: RoomModel) -> RemovedReason:
    if room.status == "cancelled":
        return "cancelled"
    if room.status != "open":
        return "started"
    if room.visibility != "public":
        return "not_public"
    if is_past_cutoff(room):
        return "past_cutoff"
    return "full"


'''
Works out which events to send and on which district channel, by comparing the
room before the change with the room now.
  was shown, still shown, same district  -> room_updated (only if something shown changed)
  was shown, still shown, other district -> room_removed (moved) on the old one,
                                            room_created on the new one
  was shown, no longer shown             -> room_removed on the old district
  was not shown, now shown               -> room_created
  never shown                            -> nothing (this keeps private rooms silent)
before is None for a brand new room.
'''
def events_for_change(
    db: Session, room: RoomModel, before: LobbyState | None
) -> list[LobbyMessage]:
    shown_before = before is not None and before.visible
    shown_now = is_visible_in_lobby(db, room)

    if not shown_before and not shown_now:
        return []

    events: list[LobbyMessage] = []
    moved = shown_before and before.district != room.district

    if shown_before and (not shown_now or moved):
        reason = "moved" if shown_now else removal_reason(room)
        events.append((before.district, RoomRemovedEvent(room_id=room.id, reason=reason)))

    if shown_now:
        payload = to_lobby_room(db, room)
        if shown_before and not moved:
            # Nothing the lobby shows changed (e.g. a pending request), so stay quiet
            if payload != before.room:
                events.append((room.district, RoomUpdatedEvent(room=payload)))
        else:
            events.append((room.district, RoomCreatedEvent(room=payload)))

    return events


# Same as events_for_change, but a failure here only means no events, never an error
def prepare_room_events(
    db: Session, room: RoomModel, before: LobbyState | None = None
) -> list[LobbyMessage]:
    try:
        return events_for_change(db, room, before)
    except Exception:
        logger.exception("Could not prepare lobby events for room %s", room.id)
        return []


# Sends ready-made events. It needs no database session, so it can run after the
# response. It never raises: a lobby problem must not break the request.
async def send_events(events: list[LobbyMessage], hub: LobbyHub | None = None) -> None:
    target = hub or lobby_hub
    for district, event in events:
        try:
            await target.broadcast(district, event)
        except Exception:
            logger.exception("Could not send lobby event %s to %s", event, district)


'''
What controllers call, after db.commit(), with the state taken before the change.
The events are worked out now, while the session is open, and sent by FastAPI
after the response has been returned, so a slow or broken socket cannot delay
or break the request.
'''
def queue_room_events(
    background_tasks: BackgroundTasks,
    db: Session,
    room: RoomModel,
    before: LobbyState | None = None,
) -> None:
    events = prepare_room_events(db, room, before)
    if events:
        background_tasks.add_task(send_events, events)
