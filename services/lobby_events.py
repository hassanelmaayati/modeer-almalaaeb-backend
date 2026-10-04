import logging
from dataclasses import dataclass

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


# What a room looked like to the lobby at one moment
@dataclass(frozen=True)
class LobbyState:
    district: str
    visible: bool


'''
A room is shown in the lobby only if the REST list would show it (public, open,
before the cutoff) and it still has a free place. Private and group rooms are
never visible, so nothing about them can reach the lobby.
'''
def is_visible_in_lobby(db: Session, room: RoomModel) -> bool:
    return is_listable(room) and count_slots_left(db, room) > 0


# Call this BEFORE changing the room, then hand it to publish_room_event afterwards
def lobby_state(db: Session, room: RoomModel) -> LobbyState:
    return LobbyState(district=room.district, visible=is_visible_in_lobby(db, room))


def to_lobby_room(db: Session, room: RoomModel) -> LobbyRoomSchema:
    # Public fields only, built one by one so a new column can never leak by accident
    return LobbyRoomSchema(
        id=room.id,
        title=room.title,
        sport_id=room.sport_id,
        sport_name=room.sport.name,
        district=room.district,
        public_area=room.public_area,
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
  was shown, still shown, same district  -> room_updated
  was shown, still shown, other district -> room_removed (moved) on the old one,
                                            room_created on the new one
  was shown, no longer shown             -> room_removed on the old district
  was not shown, now shown               -> room_created
  never shown                            -> nothing (this keeps private rooms silent)
before is None for a brand new room.
'''
def events_for_change(
    db: Session, room: RoomModel, before: LobbyState | None
) -> list[tuple[str, BaseModel]]:
    shown_before = before is not None and before.visible
    shown_now = is_visible_in_lobby(db, room)

    if not shown_before and not shown_now:
        return []

    events: list[tuple[str, BaseModel]] = []
    moved = shown_before and before.district != room.district

    if shown_before and (not shown_now or moved):
        reason = "moved" if shown_now else removal_reason(room)
        events.append((before.district, RoomRemovedEvent(room_id=room.id, reason=reason)))

    if shown_now:
        payload = to_lobby_room(db, room)
        if shown_before and not moved:
            events.append((room.district, RoomUpdatedEvent(room=payload)))
        else:
            events.append((room.district, RoomCreatedEvent(room=payload)))

    return events


'''
The one function controllers call to tell the lobby about a room change.
Call it after db.commit(), with the same session, and pass the state taken
before the change. It never raises: a lobby problem must not break the request.
'''
async def publish_room_event(
    db: Session,
    room: RoomModel,
    before: LobbyState | None = None,
    *,
    hub: LobbyHub | None = None,
) -> None:
    try:
        target = hub or lobby_hub
        for district, event in events_for_change(db, room, before):
            await target.broadcast(district, event)
    except Exception:
        logger.exception("Could not publish lobby event for room %s", room.id)
