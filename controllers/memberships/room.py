from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.membership import MembershipModel
from models.room import RoomModel
from models.user import UserModel
from services.lobby_events import lobby_state, queue_room_events
from serializers.membership import (
    RoomMemberSchema,
    CreateRoomMemberSchema,
    UpdateRoomMemberSchema,
)

router = APIRouter(
    tags=[
        "Room Members Management",
    ]
)


def _get_host_id(db: Session, room_id: int) -> int:
    from models.room import RoomModel

    room = db.query(RoomModel).filter(RoomModel.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room.host_id


def _get_room(db: Session, room_id: int) -> RoomModel:
    return db.query(RoomModel).filter(RoomModel.id == room_id).first()


def _room_membership(db: Session, room_id: int, user_id: int):
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.room_id == room_id,
            MembershipModel.user_id == user_id,
        )
        .first()
    )


@router.get("/rooms/{room_id}/members", response_model=List[RoomMemberSchema])
def get_room_members(room_id: int, db: Session = Depends(get_db)):
    return db.query(MembershipModel).filter(MembershipModel.room_id == room_id).all()


@router.post(
    "/rooms/{room_id}/members", response_model=RoomMemberSchema, status_code=201
)
def create_room_member(
    room_id: int,
    membership: CreateRoomMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    host_id = _get_host_id(db, room_id)
    target_id = membership.user_id or current_user.id
    is_self = target_id == current_user.id

    # Only the host may invite someone else; anyone may ask to join
    if not is_self:
        if current_user.id != host_id:
            raise HTTPException(status_code=403, detail="Only the host can invite")
        if not db.query(UserModel).filter(UserModel.id == target_id).first():
            raise HTTPException(status_code=404, detail="User not found")

    if _room_membership(db, room_id, target_id):
        raise HTTPException(status_code=409, detail="Already requested or a member")

    new_membership = MembershipModel(
        user_id=target_id,
        room_id=room_id,
        status="pending",
        # requested=True: the player asked (host approves); False: host invited
        requested=is_self,
        accepted=False,
    )
    db.add(new_membership)
    db.commit()
    db.refresh(new_membership)
    return new_membership


@router.patch("/rooms/{room_id}/members/{user_id}", response_model=RoomMemberSchema)
def update_room_member(
    room_id: int,
    user_id: int,
    membership: UpdateRoomMemberSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    host_id = _get_host_id(db, room_id)
    db_member = _room_membership(db, room_id, user_id)
    if not db_member:
        raise HTTPException(status_code=404, detail="Room member not found")

    data = membership.model_dump(exclude_unset=True)
    is_host = current_user.id == host_id
    is_self = current_user.id == user_id
    if not (is_host or is_self):
        raise HTTPException(status_code=403, detail="Not allowed")

    # How the lobby saw the room before this change (accepting or removing a
    # player changes the free places)
    room = _get_room(db, room_id)
    before = lobby_state(db, room)

    if "status" in data and data["status"] is not None:
        new_status = data["status"]
        old_status = db_member.status
        if is_host and old_status == "pending" and db_member.requested:
            allowed = ("accepted", "declined")
        elif is_self and old_status == "pending" and not db_member.requested:
            allowed = ("accepted", "declined")
        else:
            allowed = ()
        if is_host and not is_self and old_status in ("pending", "accepted"):
            allowed += ("removed",)
        if is_self and old_status in ("pending", "accepted"):
            allowed += ("left",)
        if new_status not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Cannot change status from {old_status} to {new_status}",
            )
        db_member.status = new_status
        db_member.accepted = new_status == "accepted"
        if new_status in ("declined", "left", "removed"):
            db_member.position = None

    if "position" in data:
        if db_member.status != "accepted":
            raise HTTPException(status_code=409, detail="Only accepted players have a slot")
        if data["position"] is not None:
            taken = (
                db.query(MembershipModel)
                .filter(
                    MembershipModel.room_id == room_id,
                    MembershipModel.status == "accepted",
                    MembershipModel.position == data["position"],
                    MembershipModel.id != db_member.id,
                )
                .first()
            )
            if taken:
                raise HTTPException(status_code=409, detail="Slot already taken")
        db_member.position = data["position"]

    if "attendance" in data and data["attendance"] is not None:
        if not is_host:
            raise HTTPException(status_code=403, detail="Only the host records attendance")
        db_member.attendance = data["attendance"]

    if "rating" in data and data["rating"] is not None:
        if not is_host:
            raise HTTPException(status_code=403, detail="Only the host can rate")
        if is_self:
            raise HTTPException(status_code=403, detail="Cannot rate yourself")
        if db_member.attendance != "present":
            raise HTTPException(status_code=409, detail="Rate only present players")
        db_member.rating = data["rating"]

    db.commit()
    db.refresh(db_member)
    queue_room_events(background_tasks, db, room, before)
    return db_member


@router.delete("/rooms/{room_id}/members/me", status_code=204)
def leave_room(
    room_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_member = _room_membership(db, room_id, current_user.id)
    if not db_member:
        raise HTTPException(status_code=404, detail="Room member not found")
    room = _get_room(db, room_id)
    before = lobby_state(db, room)

    # Keep the row for history; release the slot
    db_member.status = "left"
    db_member.position = None
    db_member.accepted = False
    db.commit()
    queue_room_events(background_tasks, db, room, before)
