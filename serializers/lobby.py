from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Why a room left a district lobby (room_removed)
RemovedReason = Literal["cancelled", "started", "full", "past_cutoff", "moved", "not_public"]


# What anyone watching a district lobby may see about a room.
# Public fields only: never venue_details, host_id, group_id or member data.
# slots_left is worked out by the server, it is not a column on the room.
class LobbyRoomSchema(BaseModel):
    id: int
    title: str
    sport_id: int
    sport_name: str
    district: str
    public_area: str
    starts_at: datetime
    capacity: int
    slots_left: int
    difficulty: str
    # Lets a client ignore an event that is older than what it already has
    revision: int


# room_created and room_updated carry the whole room, so the client just replaces it
class RoomCreatedEvent(BaseModel):
    type: Literal["room_created"] = "room_created"
    room: LobbyRoomSchema


class RoomUpdatedEvent(BaseModel):
    type: Literal["room_updated"] = "room_updated"
    room: LobbyRoomSchema


# room_removed needs only the id and why; the channel it is sent on is the district
class RoomRemovedEvent(BaseModel):
    type: Literal["room_removed"] = "room_removed"
    room_id: int
    reason: RemovedReason


# Everything the server can send on a lobby socket, told apart by "type"
LobbyEvent = Annotated[
    RoomCreatedEvent | RoomUpdatedEvent | RoomRemovedEvent,
    Field(discriminator="type"),
]
