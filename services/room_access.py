"""One rule for who may know a room exists, used by every room route.

A hidden room answers 404 "Room not found" exactly like a missing one, so
nobody can probe for private rooms by comparing error messages.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.group import GroupModel
from models.membership import MembershipModel
from models.room import RoomModel
from services.chat_access import group_user_ids
from services.memberships import load


def valid_positions(room: RoomModel) -> set[str]:
    """Slot names a player may claim: the layout's, or numbered places 1..capacity."""
    from serializers.fields import slot_names

    names = slot_names(room.slot_layout)
    return set(names) if names else {str(number) for number in range(1, room.capacity + 1)}


def viewer_group_ids(db: Session, user_id: int):
    """Subquery: groups the user owns or belongs to (accepted)."""
    owned = db.query(GroupModel.id).filter(GroupModel.owner_id == user_id)
    joined = db.query(MembershipModel.group_id).filter(
        MembershipModel.user_id == user_id,
        MembershipModel.status == "accepted",
        MembershipModel.group_id.is_not(None),
        MembershipModel.cup_id.is_(None),
    )
    return owned.union(joined)


def can_view_room(db: Session, room: RoomModel, user_id: int | None) -> bool:
    if room.visibility == "public":
        return True
    if user_id is None:
        return False
    if user_id == room.host_id:
        return True
    own = db.query(MembershipModel).filter(
        MembershipModel.room_id == room.id, MembershipModel.user_id == user_id
    ).first()
    # Admitted players and invited users know the room
    if own is not None and (own.status == "accepted" or (own.status == "pending" and not own.requested)):
        return True
    # A group-only room is visible to its group's owner and accepted members
    return room.visibility == "group" and room.group_id is not None and user_id in group_user_ids(db, room.group_id)


def load_visible_room(db: Session, room_id: int, user, *, lock: bool = False) -> RoomModel:
    room = load(db, RoomModel, room_id, lock=lock)
    if not can_view_room(db, room, user.id if user is not None else None):
        raise HTTPException(status_code=404, detail="Room not found")
    return room
