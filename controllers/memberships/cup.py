from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.group import GroupModel
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import (
    CupMemberSchema,
    CreateCupMemberSchema,
    UpdateCupMemberSchema,
)

router = APIRouter(tags=["Cup Roster Management"])


@router.post("/cups/{cup_id}/roster", response_model=CupMemberSchema, status_code=201)
def invite_cup_roster_member(
    cup_id: int,
    member: CreateCupMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    group = db.query(GroupModel).filter(GroupModel.id == member.group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Team not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the team owner can invite")

    # Invitee must be an accepted member of the team
    team_member = (
        db.query(MembershipModel)
        .filter(
            MembershipModel.group_id == member.group_id,
            MembershipModel.cup_id.is_(None),
            MembershipModel.user_id == member.user_id,
            MembershipModel.status == "accepted",
        )
        .first()
    )
    if not team_member:
        raise HTTPException(status_code=400, detail="User is not an accepted team member")
    if (
        db.query(MembershipModel)
        .filter(
            MembershipModel.cup_id == cup_id,
            MembershipModel.user_id == member.user_id,
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail="Already on the roster")

    new_member = MembershipModel(
        user_id=member.user_id,
        group_id=member.group_id,
        cup_id=cup_id,
        status="pending",
        requested=False,
        accepted=False,
    )
    db.add(new_member)
    db.commit()
    db.refresh(new_member)
    return new_member


@router.patch("/cups/{cup_id}/roster/{user_id}", response_model=CupMemberSchema)
def update_cup_roster_member(
    cup_id: int,
    user_id: int,
    member: UpdateCupMemberSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_member = (
        db.query(MembershipModel)
        .filter(MembershipModel.cup_id == cup_id, MembershipModel.user_id == user_id)
        .first()
    )
    if not db_member:
        raise HTTPException(status_code=404, detail="Roster member not found")
    if member.status is None:
        raise HTTPException(status_code=422, detail="status is required")

    group = db.query(GroupModel).filter(GroupModel.id == db_member.group_id).first()
    is_self = user_id == current_user.id
    is_owner = group is not None and group.owner_id == current_user.id
    allowed = ("accepted", "declined", "left") if is_self else ("removed",)
    if not (is_self or is_owner) or member.status not in allowed:
        raise HTTPException(status_code=403, detail="Not allowed")

    if member.status == "accepted" and (
        db.query(MembershipModel)
        .filter(
            MembershipModel.cup_id == cup_id,
            MembershipModel.user_id == user_id,
            MembershipModel.accepted.is_(True),
        )
        .first()
    ):
        raise HTTPException(status_code=409, detail="Already accepted on a team")

    db_member.status = member.status
    db_member.accepted = member.status == "accepted"
    db.commit()
    db.refresh(db_member)
    return db_member
