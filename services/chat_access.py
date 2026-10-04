from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from models.group import GroupModel
from models.membership import MembershipModel
from models.room import RoomModel
from models.user import UserModel
from services.memberships import load


def room_user_ids(db: Session, room_id: int) -> set[int]:
    room = db.get(RoomModel, room_id)
    if not room:
        return set()
    members = db.query(MembershipModel.user_id).filter(MembershipModel.room_id == room_id, MembershipModel.status == "accepted")
    return {room.host_id, *(row.user_id for row in members)}


def group_user_ids(db: Session, group_id: int) -> set[int]:
    group = db.get(GroupModel, group_id)
    if not group:
        return set()
    members = db.query(MembershipModel.user_id).filter(MembershipModel.group_id == group_id, MembershipModel.cup_id.is_(None), MembershipModel.status == "accepted")
    return {group.owner_id, *(row.user_id for row in members)}


def require_chat_access(db: Session, user_id: int, target: dict):
    kind, target_id = target["type"], target["id"]
    if kind == "room":
        load(db, RoomModel, target_id)
        permitted = user_id in room_user_ids(db, target_id)
    elif kind == "group":
        load(db, GroupModel, target_id)
        permitted = user_id in group_user_ids(db, target_id)
    elif kind == "direct":
        load(db, UserModel, target_id)
        permitted = target_id != user_id
    else:
        permitted = False
    if not permitted:
        raise HTTPException(status_code=403, detail="You do not have access to this chat")


def friendship(db: Session, a: int, b: int, *, lock=False):
    query = db.query(MembershipModel).filter(
        MembershipModel.room_id.is_(None), MembershipModel.group_id.is_(None), MembershipModel.cup_id.is_(None),
        or_((MembershipModel.user_id == a) & (MembershipModel.other_user_id == b),
            (MembershipModel.user_id == b) & (MembershipModel.other_user_id == a)),
    )
    return (query.with_for_update().populate_existing() if lock else query).first()


def require_direct_send(db: Session, sender_id: int, recipient_id: int):
    if sender_id == recipient_id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")
    load(db, UserModel, recipient_id)
    connection = friendship(db, sender_id, recipient_id, lock=True)
    if not connection or connection.status != "accepted":
        raise HTTPException(status_code=403, detail="You can only message accepted friends")
    def blocked(flag):
        return flag is not None and flag.strip().lower() not in ("", "false", "0", "no", "none")
    if blocked(connection.user_blocked_other) or blocked(connection.other_blocked_user):
        raise HTTPException(status_code=403, detail="Messaging is blocked")
