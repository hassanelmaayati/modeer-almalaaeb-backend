from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import CreateFriendSchema, FriendSchema, UpdateFriendSchema
from services.changes import change_events
from services.memberships import commit, load
from services.realtime import queue_events

router = APIRouter(tags=["Friends Management"])


def friendship(db, a, b):
    return db.query(MembershipModel).filter(MembershipModel.room_id.is_(None),
        MembershipModel.group_id.is_(None), MembershipModel.cup_id.is_(None),
        or_((MembershipModel.user_id == a) & (MembershipModel.other_user_id == b),
            (MembershipModel.user_id == b) & (MembershipModel.other_user_id == a))).with_for_update().first()


@router.get("/friends", response_model=list[FriendSchema])
def get_friends(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    return db.query(MembershipModel).filter(MembershipModel.other_user_id.is_not(None),
        or_(MembershipModel.user_id == current_user.id,
            MembershipModel.other_user_id == current_user.id)).all()


@router.post("/friends", response_model=FriendSchema, status_code=201)
def create_friend_request(friend: CreateFriendSchema, background_tasks: BackgroundTasks,
                          db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    if friend.other_user_id == current_user.id:
        raise HTTPException(400, "Cannot befriend yourself")
    load(db, UserModel, friend.other_user_id)
    if friendship(db, current_user.id, friend.other_user_id):
        raise HTTPException(409, "Friendship already exists")
    row = MembershipModel(user_id=current_user.id, other_user_id=friend.other_user_id,
                          status="pending", requested=True, accepted=False)
    db.add(row)
    events = change_events(db, {"type": "direct", "id": friend.other_user_id},
                          "friend.request", "You received a friend request", current_user.id)
    commit(db)
    db.refresh(row)
    queue_events(background_tasks, events)
    return row


@router.patch("/friends/{user_id}", response_model=FriendSchema)
def update_friend(user_id: int, friend: UpdateFriendSchema, background_tasks: BackgroundTasks,
                  db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    row = friendship(db, current_user.id, user_id)
    if not row:
        raise HTTPException(404, "Friendship not found")
    data = friend.model_dump(exclude_unset=True)
    requester = row.user_id == current_user.id
    own_flag = "user_blocked_other" if requester else "other_blocked_user"
    other_flag = "other_blocked_user" if requester else "user_blocked_other"
    if other_flag in data:
        raise HTTPException(403, "Cannot change the other's block")
    if "status" in data:
        allowed = (("left",) if requester else ("accepted", "declined")) if row.status == "pending" else ()
        if row.status == "accepted":
            allowed += ("left",)
        if data["status"] not in allowed:
            raise HTTPException(403, "This friendship transition is not allowed")
        row.status, row.accepted = data["status"], data["status"] == "accepted"
    if own_flag in data:
        setattr(row, own_flag, data[own_flag])
    events = change_events(db, {"type": "direct", "id": user_id}, "friend.updated",
                          "A friendship was updated", current_user.id)
    commit(db)
    db.refresh(row)
    queue_events(background_tasks, events)
    return row
