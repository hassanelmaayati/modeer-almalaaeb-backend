from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session
from database import get_db
from dependencies.get_current_user import get_current_user
from models.group import GroupModel
from models.membership import MembershipModel
from models.message import MessageModel
from models.room import RoomModel
from models.user import UserModel
from serializers.message import ConversationSchema, CreateMessageSchema, MessageSchema
from services.chat_access import require_chat_access
from services.memberships import load
from services.messages import save_message
from services.realtime import queue_events

router = APIRouter(tags=["Messages Management"])


def latest_ids(column, condition):
    return select(func.max(MessageModel.id)).where(condition).group_by(column)


@router.get("/messages/conversations", response_model=list[ConversationSchema])
def get_conversations(limit: int = Query(50, ge=1, le=100), include_empty: bool = False,
                      db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    me = current_user.id
    hosted = select(RoomModel.id).where(RoomModel.host_id == me)
    joined_rooms = select(MembershipModel.room_id).where(MembershipModel.user_id == me, MembershipModel.status == "accepted", MembershipModel.room_id.isnot(None))
    owned_groups = select(GroupModel.id).where(GroupModel.owner_id == me)
    joined_groups = select(MembershipModel.group_id).where(MembershipModel.user_id == me, MembershipModel.status == "accepted", MembershipModel.group_id.isnot(None), MembershipModel.cup_id.is_(None))
    rooms = latest_ids(MessageModel.room_id, or_(MessageModel.room_id.in_(hosted), MessageModel.room_id.in_(joined_rooms)))
    groups = latest_ids(MessageModel.group_id, or_(MessageModel.group_id.in_(owned_groups), MessageModel.group_id.in_(joined_groups)))
    partner = case((MessageModel.sender_id == me, MessageModel.recipient_id), else_=MessageModel.sender_id)
    direct = latest_ids(partner, (MessageModel.type == "direct") & or_(MessageModel.sender_id == me, MessageModel.recipient_id == me))
    messages = db.query(MessageModel).filter(or_(MessageModel.id.in_(rooms), MessageModel.id.in_(groups), MessageModel.id.in_(direct))).order_by(MessageModel.id.desc()).limit(limit).all()
    conversations = []
    for message in messages:
        if message.room_id is not None:
            target = {"type": "room", "room_id": message.room_id, "title": message.room.title}
        elif message.group_id is not None:
            target = {"type": "group", "group_id": message.group_id, "title": message.group.name}
        else:
            other = message.recipient if message.sender_id == me else message.sender
            target = {"type": "direct", "user_id": other.id, "title": other.user_name}
        conversations.append(ConversationSchema(**target, last_message=MessageSchema.model_validate(message)))
    if include_empty:
        seen = {(item.type, item.room_id or item.group_id or item.user_id) for item in conversations}
        targets = [("room", row.id, row.title) for row in db.query(RoomModel).filter(or_(RoomModel.id.in_(hosted), RoomModel.id.in_(joined_rooms))).order_by(RoomModel.id)]
        targets += [("group", row.id, row.name) for row in db.query(GroupModel).filter(or_(GroupModel.id.in_(owned_groups), GroupModel.id.in_(joined_groups))).order_by(GroupModel.id)]
        friends = db.query(MembershipModel).filter(MembershipModel.room_id.is_(None), MembershipModel.group_id.is_(None), MembershipModel.cup_id.is_(None), MembershipModel.status == "accepted", or_(MembershipModel.user_id == me, MembershipModel.other_user_id == me))
        friend_ids = {row.other_user_id if row.user_id == me else row.user_id for row in friends}
        targets += [("direct", row.id, row.user_name) for row in db.query(UserModel).filter(UserModel.id.in_(friend_ids)).order_by(UserModel.id)]
        for kind, target_id, title in targets:
            if (kind, target_id) not in seen:
                field = {"room": "room_id", "group": "group_id", "direct": "user_id"}[kind]
                conversations.append(ConversationSchema(type=kind, title=title, **{field: target_id}))
    return conversations[:limit]


@router.get("/messages", response_model=list[MessageSchema])
def get_messages(room_id: int | None = None, user_id: int | None = None, group_id: int | None = None,
                 before: int | None = Query(None, description="Only messages older than this id"), limit: int = Query(50, ge=1, le=100),
                 db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    if sum(value is not None for value in (room_id, user_id, group_id)) != 1:
        raise HTTPException(status_code=422, detail="Send exactly one of room_id, user_id or group_id")
    query = db.query(MessageModel)
    if room_id is not None:
        require_chat_access(db, current_user.id, {"type": "room", "id": room_id})
        query = query.filter(MessageModel.room_id == room_id)
    elif group_id is not None:
        require_chat_access(db, current_user.id, {"type": "group", "id": group_id})
        query = query.filter(MessageModel.group_id == group_id)
    else:
        # Old direct history remains readable after unfriend/block.
        load(db, UserModel, user_id)
        me = current_user.id
        query = query.filter(MessageModel.type == "direct", or_(
            (MessageModel.sender_id == me) & (MessageModel.recipient_id == user_id),
            (MessageModel.sender_id == user_id) & (MessageModel.recipient_id == me)))
    if before is not None:
        query = query.filter(MessageModel.id < before)
    return query.order_by(MessageModel.id.desc()).limit(limit).all()


@router.post("/messages", response_model=MessageSchema, status_code=201)
def create_message(message: CreateMessageSchema, response: Response, background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    saved, created, events = save_message(db, current_user, message)
    response.status_code = 201 if created else 200
    queue_events(background_tasks, events)
    return saved
