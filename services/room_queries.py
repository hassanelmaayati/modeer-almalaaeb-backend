from dataclasses import dataclass
from datetime import datetime
from typing import List

from fastapi import HTTPException, Query

from models.room import DIFFICULTY, ROOM_STATUSES, ROOM_VISIBILITIES, RoomModel
from services.room_rules import as_utc

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass
class RoomListParams:
    status: List[str] | None
    sport_id: int | None
    visibility: str | None
    difficulty: str | None
    starts_from: datetime | None
    starts_to: datetime | None
    order: str
    limit: int
    offset: int


def room_list_params(
    status: List[str] | None = Query(default=None),
    sport_id: int | None = None,
    visibility: str | None = None,
    difficulty: str | None = None,
    starts_from: datetime | None = None,
    starts_to: datetime | None = None,
    order: str = "asc",
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> RoomListParams:
    for values, allowed, name in (
        (status or [], ROOM_STATUSES, "status"),
        ([visibility] if visibility else [], ROOM_VISIBILITIES, "visibility"),
        ([difficulty] if difficulty else [], DIFFICULTY, "difficulty"),
        ([order], ("asc", "desc"), "order"),
    ):
        if any(value not in allowed for value in values):
            raise HTTPException(
                status_code=422,
                detail=f"{name} must be one of: {', '.join(allowed)}",
            )
    return RoomListParams(
        status=status,
        sport_id=sport_id,
        visibility=visibility,
        difficulty=difficulty,
        starts_from=starts_from,
        starts_to=starts_to,
        order=order,
        limit=limit,
        offset=offset,
    )


def filter_rooms(query, params: RoomListParams):
    if params.status:
        query = query.filter(RoomModel.status.in_(params.status))
    if params.sport_id is not None:
        query = query.filter(RoomModel.sport_id == params.sport_id)
    if params.visibility is not None:
        query = query.filter(RoomModel.visibility == params.visibility)
    if params.difficulty is not None:
        query = query.filter(RoomModel.difficulty == params.difficulty)
    if params.starts_from is not None:
        query = query.filter(RoomModel.starts_at >= as_utc(params.starts_from))
    if params.starts_to is not None:
        query = query.filter(RoomModel.starts_at <= as_utc(params.starts_to))
    return query


def page_rooms(query, params: RoomListParams):
    query = filter_rooms(query, params)
    total = query.count()
    starts_at = RoomModel.starts_at.desc() if params.order == "desc" else RoomModel.starts_at
    rooms = query.order_by(starts_at, RoomModel.id).offset(params.offset).limit(params.limit).all()
    return rooms, total


def page_payload(items, total: int, params: RoomListParams) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
        "has_more": params.offset + len(items) < total,
    }
