from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.cup import CupModel
from models.group import GroupModel
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import CreateCupMemberSchema, CupMemberSchema, UpdateCupMemberSchema
from services.changes import change_events
from services.memberships import commit, invitation_transition, load
from services.realtime import queue_events

router = APIRouter(tags=["Cup Roster Management"])


def roster(db, cup_id):
    return db.query(MembershipModel).filter(MembershipModel.cup_id == cup_id)


def registration_cup(db, cup_id):
    cup = load(db, CupModel, cup_id, lock=True)
    if cup.status != "registration" or cup.rosters_locked_at is not None:
        raise HTTPException(409, "The roster is closed")
    return cup


def require_team_member(db, group, user_id):
    if user_id != group.owner_id and not db.query(MembershipModel).filter(
            MembershipModel.group_id == group.id, MembershipModel.cup_id.is_(None),
            MembershipModel.user_id == user_id, MembershipModel.status == "accepted").first():
        raise HTTPException(400, "User is not an accepted team member")


def require_entry(cup, group_id):
    if not any(e["group_id"] == group_id and e["status"] in ("pending", "accepted") for e in cup.entries):
        raise HTTPException(409, "The team is not entered in this cup")


@router.post("/cups/{cup_id}/roster", response_model=CupMemberSchema, status_code=201)
def invite_cup_roster_member(cup_id: int, member: CreateCupMemberSchema,
                            background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                            current_user: UserModel = Depends(get_current_user)):
    cup = registration_cup(db, cup_id)
    group = load(db, GroupModel, member.group_id, lock=True)
    if group.owner_id != current_user.id:
        raise HTTPException(403, "Only the team owner can invite")
    require_entry(cup, group.id)
    load(db, UserModel, member.user_id)
    require_team_member(db, group, member.user_id)
    if roster(db, cup_id).filter(MembershipModel.user_id == member.user_id).first():
        raise HTTPException(409, "Already on the roster")
    row = MembershipModel(user_id=member.user_id, group_id=group.id, cup_id=cup_id,
                          status="pending", requested=False, accepted=False)
    db.add(row)
    events = change_events(db, {"type": "cup", "id": cup_id}, "cup.invitation",
                          "You were invited to a cup roster", current_user.id,
                          recipient_ids={current_user.id, member.user_id})
    commit(db)
    db.refresh(row)
    queue_events(background_tasks, events)
    return row


@router.patch("/cups/{cup_id}/roster/{user_id}", response_model=CupMemberSchema)
def update_cup_roster_member(cup_id: int, user_id: int, member: UpdateCupMemberSchema,
                            background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                            current_user: UserModel = Depends(get_current_user)):
    cup = registration_cup(db, cup_id)
    row = roster(db, cup_id).filter(MembershipModel.user_id == user_id).first()
    if not row:
        raise HTTPException(404, "Roster member not found")
    if member.status is None:
        raise HTTPException(422, "status is required")
    group = load(db, GroupModel, row.group_id, lock=True)
    invitation_transition(row, member.status, is_self=user_id == current_user.id,
                          is_owner=group.owner_id == current_user.id)
    if member.status == "accepted":
        require_entry(cup, group.id)
        require_team_member(db, group, user_id)
        if roster(db, cup_id).filter(MembershipModel.group_id == group.id,
                                     MembershipModel.status == "accepted",
                                     MembershipModel.id != row.id).count() >= cup.roster_limit:
            raise HTTPException(409, "The team roster is full")
    events = change_events(db, {"type": "cup", "id": cup_id}, "cup.roster",
                          "A cup roster was updated", current_user.id, extra_ids=[user_id])
    commit(db)
    db.refresh(row)
    queue_events(background_tasks, events)
    return row
