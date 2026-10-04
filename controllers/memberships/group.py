from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.group import GroupModel
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import (
    GroupMemberSchema,
    CreateGroupMemberSchema,
    UpdateGroupMemberSchema,
)

router = APIRouter(tags=["Group Members Management"])


def _get_group(db: Session, group_id: int) -> GroupModel:
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def _group_members(db: Session, group_id: int):
    return db.query(MembershipModel).filter(
        MembershipModel.group_id == group_id,
        MembershipModel.cup_id.is_(None),
    )


@router.get("/groups/{group_id}/members", response_model=List[GroupMemberSchema])
def get_group_members(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    group = _get_group(db, group_id)
    query = _group_members(db, group_id)
    if group.owner_id != current_user.id:
        # Non-owners see accepted members and their own invitation
        query = query.filter(
            (MembershipModel.status == "accepted")
            | (MembershipModel.user_id == current_user.id)
        )
    # Owners see all members
    return query.all()


@router.post(
    "/groups/{group_id}/members", response_model=GroupMemberSchema, status_code=201
)
def invite_group_member(
    group_id: int,
    member: CreateGroupMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    group = _get_group(db, group_id)
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can invite")
    if not db.query(UserModel).filter(UserModel.id == member.user_id).first():
        raise HTTPException(status_code=404, detail="User not found")
    if (
        _group_members(db, group_id)
        .filter(MembershipModel.user_id == member.user_id)
        .first()
    ):
        raise HTTPException(status_code=409, detail="Already a member or invited")

    new_member = MembershipModel(
        user_id=member.user_id,
        group_id=group_id,
        status="pending",
        requested=False,
        accepted=False,
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    return new_member


@router.patch("/groups/{group_id}/members/{user_id}", response_model=GroupMemberSchema)
def update_group_member(
    group_id: int,
    user_id: int,
    member: UpdateGroupMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    group = _get_group(db, group_id)
    db_member = (
        _group_members(db, group_id).filter(MembershipModel.user_id == user_id).first()
    )
    if not db_member:
        raise HTTPException(status_code=404, detail="Group member not found")
    if member.status is None:
        raise HTTPException(status_code=422, detail="status is required")

    is_self = user_id == current_user.id
    is_owner = group.owner_id == current_user.id
    allowed = ("accepted", "declined", "left") if is_self else ("removed",)
    if not (is_self or is_owner) or member.status not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed")

    db_member.status = member.status
    db_member.accepted = member.status == "accepted"
    db.commit()
    db.refresh(db_member)
    return db_member
