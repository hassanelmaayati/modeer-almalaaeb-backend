from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.group import GroupModel
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import CreateGroupMemberSchema, GroupMemberSchema, UpdateGroupMemberSchema
from services.changes import change_events
from services.memberships import commit, invitation_transition, load
from services.realtime import queue_events

router = APIRouter(tags=["Group Members Management"])


def members(db, group_id):
    return db.query(MembershipModel).filter(MembershipModel.group_id == group_id,
                                            MembershipModel.cup_id.is_(None))


@router.get("/groups/{group_id}/members", response_model=list[GroupMemberSchema])
def get_group_members(group_id: int, db: Session = Depends(get_db),
                      current_user: UserModel = Depends(get_current_user)):
    group = load(db, GroupModel, group_id)
    query = members(db, group_id)
    if group.owner_id != current_user.id:
        query = query.filter((MembershipModel.status == "accepted") |
                             (MembershipModel.user_id == current_user.id))
    return query.all()


@router.post("/groups/{group_id}/members", response_model=GroupMemberSchema, status_code=201)
def invite_group_member(group_id: int, member: CreateGroupMemberSchema,
                        background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                        current_user: UserModel = Depends(get_current_user)):
    group = load(db, GroupModel, group_id, lock=True)
    if group.owner_id != current_user.id:
        raise HTTPException(403, "Only the owner can invite")
    load(db, UserModel, member.user_id)
    if member.user_id == group.owner_id or members(db, group_id).filter(
            MembershipModel.user_id == member.user_id).first():
        raise HTTPException(409, "Already a member or invited")
    new_member = MembershipModel(user_id=member.user_id, group_id=group_id,
                                 status="pending", requested=False, accepted=False)
    db.add(new_member)
    events = change_events(db, {"type": "group", "id": group_id}, "group.invitation",
                          "You were invited to a group", current_user.id,
                          recipient_ids={group.owner_id, member.user_id})
    commit(db)
    db.refresh(new_member)
    queue_events(background_tasks, events)
    return new_member


@router.patch("/groups/{group_id}/members/{user_id}", response_model=GroupMemberSchema)
def update_group_member(group_id: int, user_id: int, member: UpdateGroupMemberSchema,
                        background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                        current_user: UserModel = Depends(get_current_user)):
    group = load(db, GroupModel, group_id, lock=True)
    row = members(db, group_id).filter(MembershipModel.user_id == user_id).first()
    if not row:
        raise HTTPException(404, "Group member not found")
    if member.status is None:
        raise HTTPException(422, "status is required")
    invitation_transition(row, member.status, is_self=user_id == current_user.id,
                          is_owner=group.owner_id == current_user.id)
    events = change_events(db, {"type": "group", "id": group_id}, "group.membership",
                          "A group membership was updated", current_user.id, extra_ids=[user_id])
    commit(db)
    db.refresh(row)
    queue_events(background_tasks, events)
    return row
