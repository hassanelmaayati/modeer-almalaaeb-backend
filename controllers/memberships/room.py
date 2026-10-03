from fastapi import APIRouter, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.membership import MembershipModel
from models.user import UserModel

from models.room import RoomModel

# Serializers
from serializers.membership import (
    RoomMemberSchema,
    CreateRoomMemberSchema,
    UpdateRoomMemberSchema,
)
from typing import List

from dependencies.get_current_user import get_current_user

router = APIRouter(
    tags=[
        "Room Members Management",
    ]
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

    new_membership = MembershipModel(
        **membership.model_dump(), user_id=current_user.id, room_id=room_id
    )
    db.add(new_membership)
    db.commit()
    db.refresh(new_membership)
    return new_membership


# patch room member status or position or attendance or rating
@router.patch("/rooms/{room_id}/members/{member_id}", response_model=RoomMemberSchema)
def update_room_member(
    member_id: int,
    membership: UpdateRoomMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_member = (
        db.query(MembershipModel).filter(MembershipModel.id == member_id).first()
    )
    if not db_member:
        raise HTTPException(status_code=404, detail="Room member not found")

    host_id = (
        db.query(RoomModel).filter(RoomModel.id == db_member.room_id).first().host_id
    )

    if current_user.id == host_id:
        if membership.status is not None:
            db_member.status = membership.status
        if membership.attendance is not None:
            db_member.attendance = membership.attendance
        if membership.rating is not None:
            db_member.rating = membership.rating
        db.commit()
        db.refresh(db_member)
        return db_member

    if db_member.user_id == current_user.id:
        db_member.status = membership.status
        db_member.attendance = membership.attendance
        db.commit()
        db.refresh(db_member)
        return db_member

    db.commit()
    db.refresh(db_member)
    return db_member
