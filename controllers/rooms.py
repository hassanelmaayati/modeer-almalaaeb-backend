from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.areas import is_area_in_district
from models.districts import DISTRICTS
from models.room import RoomModel, make_point
from models.sport import SportModel
from models.group import GroupModel
from models.user import UserModel

# Serializers
from serializers.room import (
    RoomSchema,
    RoomDetailSchema,
    CreateRoomSchema,
    UpdateRoomSchema,
    CancelRoomSchema,
)

from dependencies.get_current_user import get_current_user
from services.lobby_events import lobby_state, queue_room_events
from services.messages import create_system_message
from services.room_rules import CUTOFF, as_utc, is_past_cutoff

router = APIRouter(
    tags=[
        "Rooms Management",
    ]
)

# Fields that are frozen once the cutoff is reached
FROZEN_FIELDS = {
    "sport_id",
    "starts_at",
    "ends_at",
    "capacity",
    "slot_layout",
    "district",
    "area",
    "venue_location",
    "venue_notes",
}

# Columns that cannot be set to null
REQUIRED_FIELDS = {
    "sport_id",
    "title",
    "difficulty",
    "starts_at",
    "ends_at",
    "capacity",
    "slot_layout",
    "visibility",
    "admission_policy",
    "district",
    "area",
}

optional_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer),
):
    # Browsing is public, so a missing token means "visitor", not an error
    if credentials is None:
        return None
    return get_current_user(db=db, token=credentials)


def get_room_or_404(db: Session, room_id: int) -> RoomModel:
    room = db.query(RoomModel).filter(RoomModel.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def get_host_room(db: Session, room_id: int, current_user: UserModel) -> RoomModel:
    room = get_room_or_404(db, room_id)
    if room.host_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only host allowed to do this!")
    return room


def split_location(data: dict) -> dict:
    # The API takes venue_location as latitude/longitude, the table stores a PostGIS point
    location = data.pop("venue_location", None)
    if location is not None:
        data["venue_point"] = make_point(location["latitude"], location["longitude"])
    return data


def check_capacity(room: RoomModel):
    try:
        room.validate_capacity()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


def check_group(db: Session, group_id: int, current_user: UserModel):
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only create rooms for your own groups"
        )


@router.get("/rooms", response_model=List[RoomSchema])
def get_rooms(
    sport_id: int | None = None,
    difficulty: str | None = None,
    district: str | None = None,
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    db: Session = Depends(get_db),
):
    # No district means all districts; an unknown one is a client mistake
    if district is not None and district not in DISTRICTS:
        raise HTTPException(
            status_code=422,
            detail=f"district must be one of: {', '.join(DISTRICTS)}",
        )

    # Discovery shows public, open rooms that are not yet past the cutoff
    cutoff_time = datetime.now(timezone.utc) + CUTOFF
    query = db.query(RoomModel).filter(
        RoomModel.status == "open",
        RoomModel.visibility == "public",
        RoomModel.starts_at > cutoff_time,
    )

    if sport_id is not None:
        query = query.filter(RoomModel.sport_id == sport_id)
    if difficulty is not None:
        query = query.filter(RoomModel.difficulty == difficulty)
    if district is not None:
        query = query.filter(RoomModel.district == district)
    if starts_from is not None:
        query = query.filter(RoomModel.starts_at >= as_utc(starts_from))
    if starts_to is not None:
        query = query.filter(RoomModel.starts_at <= as_utc(starts_to))

    return query.order_by(RoomModel.starts_at).all()


@router.get("/rooms/{room_id}", response_model=None)
def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel | None = Depends(get_optional_user),
):
    room = get_room_or_404(db, room_id)
    is_host = current_user is not None and current_user.id == room.host_id

    # Private and group rooms are hidden (members must be added later)
    if room.visibility != "public" and not is_host:
        raise HTTPException(status_code=404, detail="Room not found")

    # Only the host sees the venue location and notes for now (members must be added later)
    if is_host:
        return RoomDetailSchema.model_validate(room)
    return RoomSchema.model_validate(room)


@router.post("/rooms", response_model=RoomDetailSchema, status_code=201)
def create_room(
    room: CreateRoomSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    sport = db.query(SportModel).filter(SportModel.id == room.sport_id).first()
    if not sport:
        raise HTTPException(status_code=404, detail="Sport not found")

    if room.group_id is not None:
        check_group(db, room.group_id, current_user)

    new_room = RoomModel(**split_location(room.dict()), host_id=current_user.id, sport=sport)
    check_capacity(new_room)

    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    # Tell the lobby after the commit; it is sent once the response is on its way
    queue_room_events(background_tasks, db, new_room)
    return new_room


@router.put("/rooms/{room_id}", response_model=RoomDetailSchema)
def update_room(
    room_id: int,
    room: UpdateRoomSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_room = get_host_room(db, room_id, current_user)

    if db_room.status != "open":
        raise HTTPException(status_code=409, detail="Only open rooms can be edited")

    # A stale edit (someone changed the room since it was loaded) is rejected
    if room.revision != db_room.revision:
        raise HTTPException(
            status_code=409, detail="Room was changed, reload it and try again"
        )

    # How the lobby saw the room before this edit, to work out what changed
    before = lobby_state(db, db_room)

    data = room.dict(exclude_unset=True)
    data.pop("revision")

    for key in REQUIRED_FIELDS:
        if key in data and data[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be empty")

    if is_past_cutoff(db_room) and FROZEN_FIELDS & data.keys():
        raise HTTPException(
            status_code=409,
            detail="Schedule, venue and capacity are frozen 15 minutes before the start",
        )

    # The new start/end must still make sense together with the stored values
    starts_at = data.get("starts_at", as_utc(db_room.starts_at))
    ends_at = data.get("ends_at", as_utc(db_room.ends_at))
    if ends_at <= starts_at:
        raise HTTPException(status_code=422, detail="ends at must be after starts at")

    # The area must belong to the district, whichever of the two was sent. A
    # district change without a matching new area is rejected
    district = data.get("district", db_room.district)
    area = data.get("area", db_room.area)
    if {"district", "area"} & data.keys() and not is_area_in_district(area, district):
        raise HTTPException(
            status_code=422,
            detail=f"area '{area}' is not in the {district} district, send a matching area",
        )

    visibility = data.get("visibility", db_room.visibility)
    group_id = data.get("group_id", db_room.group_id)
    if visibility == "group" and group_id is None:
        raise HTTPException(
            status_code=422, detail="group id is required when visibility is 'group'"
        )
    if data.get("group_id") is not None:
        check_group(db, data["group_id"], current_user)

    if "sport_id" in data:
        sport = db.query(SportModel).filter(SportModel.id == data["sport_id"]).first()
        if not sport:
            raise HTTPException(status_code=404, detail="Sport not found")

    for key, value in split_location(data).items():
        setattr(db_room, key, value)

    # The sport relationship must point at the new sport before checking capacity
    if "sport_id" in data:
        db_room.sport = sport
    if {"sport_id", "capacity"} & data.keys():
        check_capacity(db_room)

    db_room.revision += 1
    db.commit()
    db.refresh(db_room)
    queue_room_events(background_tasks, db, db_room, before)
    return db_room


@router.post("/rooms/{room_id}/cancel", response_model=RoomDetailSchema)
def cancel_room(
    room_id: int,
    cancellation: CancelRoomSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_room = get_host_room(db, room_id, current_user)

    if db_room.status != "open":
        raise HTTPException(status_code=409, detail="Only open rooms can be cancelled")

    before = lobby_state(db, db_room)

    db_room.status = "cancelled"
    db_room.revision += 1

    # Tell the room's members why it was cancelled. The message is saved in the
    # same commit as the status change, and it only contains the reason
    create_system_message(
        db, db_room.id, f"Room cancelled: {cancellation.reason.strip()}"
    )
    db.commit()
    db.refresh(db_room)
    queue_room_events(background_tasks, db, db_room, before)
    return db_room
