from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.membership import MembershipModel
from models.room import RoomModel

# Discovery and schedule/venue/capacity edits close 15 minutes before the start
CUTOFF = timedelta(minutes=15)


def as_utc(value: datetime) -> datetime:
    # SQLite (used by the tests) returns naive datetimes
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def is_past_cutoff(room: RoomModel) -> bool:
    return datetime.now(timezone.utc) >= as_utc(room.starts_at) - CUTOFF


# The same rule GET /rooms applies: public, open and not yet past the cutoff.
# A full room still counts as listed here, fullness is checked separately.
def is_listable(room: RoomModel) -> bool:
    return (
        room.visibility == "public"
        and room.status == "open"
        and not is_past_cutoff(room)
    )


# Accepted players and the host each take one place, and the host counts once
# even if the host also has a membership row. Pending requests reserve nothing.
def count_slots_left(db: Session, room: RoomModel) -> int:
    taken = {
        user_id
        for (user_id,) in db.query(MembershipModel.user_id).filter(
            MembershipModel.room_id == room.id,
            MembershipModel.status == "accepted",
        )
    }
    taken.add(room.host_id)
    return max(0, room.capacity - len(taken))


def slots_left_map(db: Session, rooms) -> dict[int, int]:
    """slots_left for many rooms in one query (same rule as count_slots_left)."""
    if not rooms:
        return {}
    accepted = dict(
        db.query(MembershipModel.room_id, func.count(MembershipModel.id))
        .join(RoomModel, RoomModel.id == MembershipModel.room_id)
        .filter(
            MembershipModel.room_id.in_([room.id for room in rooms]),
            MembershipModel.status == "accepted",
            # The host takes one place however many rows they have
            MembershipModel.user_id != RoomModel.host_id,
        )
        .group_by(MembershipModel.room_id)
        .all()
    )
    return {room.id: max(0, room.capacity - accepted.get(room.id, 0) - 1) for room in rooms}
