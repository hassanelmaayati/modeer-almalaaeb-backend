from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import (
    FriendSchema,
    CreateFriendSchema,
    UpdateFriendSchema,
)

router = APIRouter(tags=["Friends Management"])


def _friendship(db: Session, a: int, b: int):
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.room_id.is_(None),
            MembershipModel.group_id.is_(None),
            MembershipModel.cup_id.is_(None),
            or_(
                (MembershipModel.user_id == a) & (MembershipModel.other_user_id == b),
                (MembershipModel.user_id == b) & (MembershipModel.other_user_id == a),
            ),
        )
        .first()
    )


@router.get("/friends", response_model=List[FriendSchema])
def get_friends(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.other_user_id.isnot(None),
            or_(
                MembershipModel.user_id == current_user.id,
                MembershipModel.other_user_id == current_user.id,
            ),
        )
        .all()
    )


@router.post("/friends", response_model=FriendSchema, status_code=201)
def create_friend_request(
    friend: CreateFriendSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    if friend.other_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot befriend yourself")
    if not db.query(UserModel).filter(UserModel.id == friend.other_user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    if _friendship(db, current_user.id, friend.other_user_id):
        raise HTTPException(status_code=409, detail="Friendship already exists")

    new_friend = MembershipModel(
        user_id=current_user.id,
        other_user_id=friend.other_user_id,
        status="pending",
        requested=True,
        accepted=False,
    )
    db.add(new_friend)
    db.commit()
    db.refresh(new_friend)
    return new_friend


@router.patch("/friends/{user_id}", response_model=FriendSchema)
def update_friend(
    user_id: int,
    friend: UpdateFriendSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_friend = _friendship(db, current_user.id, user_id)
    if not db_friend:
        raise HTTPException(status_code=404, detail="Friendship not found")

    data = friend.dict(exclude_unset=True)
    is_requester = db_friend.user_id == current_user.id

    if "status" in data:
        # Only the target user may accept or decline
        if data["status"] in ("accepted", "declined") and is_requester:
            raise HTTPException(status_code=403, detail="Only the target can respond")
        db_friend.status = data["status"]
        db_friend.accepted = data["status"] == "accepted"

    # Each user controls only their own block flag
    own_flag = "user_blocked_other" if is_requester else "other_blocked_user"
    other_flag = "other_blocked_user" if is_requester else "user_blocked_other"
    if other_flag in data:
        raise HTTPException(status_code=403, detail="Cannot change the other's block")
    if own_flag in data:
        setattr(db_friend, own_flag, data[own_flag])

    db.commit()
    db.refresh(db_friend)
    return db_friend
