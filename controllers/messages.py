from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# DB
from database import get_db

# Models
from models.membership import MembershipModel
from models.message import MessageModel
from models.room import RoomModel
from models.user import UserModel

# Serializers
from serializers.message import (
    MessageSchema,
    CreateMessageSchema,
    ConversationSchema,
)

from dependencies.get_current_user import get_current_user

router = APIRouter(
    tags=[
        "Messages Management",
    ]
)

# Chat is closed for cancelled rooms only
CLOSED_ROOM_STATUSES = ("cancelled",)

# Block flags are strings on MembershipModel, so these mean "not blocked"
NOT_BLOCKED = ("", "false", "0", "no", "none")


# True when a block flag is set to anything except the "not blocked" values
def is_blocked(flag: str | None) -> bool:
    return flag is not None and flag.strip().lower() not in NOT_BLOCKED


# Helpers that load a row or stop the request with 404
def get_room_or_404(db: Session, room_id: int) -> RoomModel:
    room = db.query(RoomModel).filter(RoomModel.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


def get_user_or_404(db: Session, user_id: int) -> UserModel:
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def is_room_member(db: Session, room: RoomModel, user: UserModel) -> bool:
    # The host counts as a member even without a membership row
    if room.host_id == user.id:
        return True
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.room_id == room.id,
            MembershipModel.user_id == user.id,
            MembershipModel.status == "accepted",
        )
        .first()
        is not None
    )


# Room chat is only for the host and accepted players, others get 403
def require_room_member(db: Session, room: RoomModel, user: UserModel):
    if not is_room_member(db, room, user):
        raise HTTPException(
            status_code=403, detail="Only the host and accepted players can use room chat"
        )


# Finds the friendship row between two users, whichever of them sent the request
def get_friendship(db: Session, a: int, b: int):
    # A friendship is a membership row between two users with no room or group
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.room_id.is_(None),
            MembershipModel.group_id.is_(None),
            or_(
                (MembershipModel.user_id == a) & (MembershipModel.other_user_id == b),
                (MembershipModel.user_id == b) & (MembershipModel.other_user_id == a),
            ),
        )
        .first()
    )


# Direct messages need an accepted friendship with no block on either side
def require_can_direct_message(db: Session, sender: UserModel, recipient_id: int):
    if recipient_id == sender.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")
    get_user_or_404(db, recipient_id)

    # Pending, declined or missing friendships cannot send messages
    friendship = get_friendship(db, sender.id, recipient_id)
    if not friendship or friendship.status != "accepted":
        raise HTTPException(
            status_code=403, detail="You can only message accepted friends"
        )
    # Either side blocking stops new messages (old ones stay readable)
    if is_blocked(friendship.user_blocked_other) or is_blocked(
        friendship.other_blocked_user
    ):
        raise HTTPException(status_code=403, detail="Messaging is blocked")


# Looks for a message this user already sent with the same client_request_id
def find_duplicate(db: Session, sender_id: int, request_id):
    return (
        db.query(MessageModel)
        .filter(
            MessageModel.sender_id == sender_id,
            MessageModel.client_request_id == request_id,
        )
        .first()
    )


# A reused client_request_id is only a retry if it points to the same target
def same_target(message: MessageModel, data: CreateMessageSchema) -> bool:
    return message.room_id == data.room_id and message.recipient_id == data.recipient_id


@router.get("/messages/conversations", response_model=List[ConversationSchema])
def get_conversations(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # The inbox: one entry per room chat and per direct chat, with the last message
    me = current_user.id

    # Rooms the user can read: hosted, or accepted member (left rooms drop out)
    hosted = select(RoomModel.id).where(RoomModel.host_id == me)
    joined = select(MembershipModel.room_id).where(
        MembershipModel.user_id == me,
        MembershipModel.room_id.isnot(None),
        MembershipModel.status == "accepted",
    )
    latest_in_rooms = (
        select(func.max(MessageModel.id))
        .where(
            MessageModel.room_id.isnot(None),
            or_(MessageModel.room_id.in_(hosted), MessageModel.room_id.in_(joined)),
        )
        .group_by(MessageModel.room_id)
    )

    # Direct chats stay listed after an unfriend or block.
    # partner is the other person in each message, so messages sent and
    # received are grouped into one chat
    partner = case((MessageModel.sender_id == me, MessageModel.recipient_id), else_=MessageModel.sender_id)
    latest_direct = (
        select(func.max(MessageModel.id))
        .where(
            MessageModel.type == "direct",
            or_(MessageModel.sender_id == me, MessageModel.recipient_id == me),
        )
        .group_by(partner)
    )

    # Load the newest message of every room and direct chat found above
    room_messages = (
        db.query(MessageModel).filter(MessageModel.id.in_(latest_in_rooms)).all()
    )
    direct_messages = (
        db.query(MessageModel).filter(MessageModel.id.in_(latest_direct)).all()
    )

    # Titles: the room name, or the other user's name for direct chats
    titles = {
        room.id: room.title
        for room in db.query(RoomModel).filter(
            RoomModel.id.in_([m.room_id for m in room_messages])
        )
    }
    partner_ids = {
        (m.recipient_id if m.sender_id == me else m.sender_id) for m in direct_messages
    }
    names = {
        user.id: user.user_name
        for user in db.query(UserModel).filter(UserModel.id.in_(partner_ids))
    }

    # Build one conversation entry for each room and direct chat
    conversations = []
    for message in room_messages:
        conversations.append(
            ConversationSchema(
                type="room",
                room_id=message.room_id,
                title=titles[message.room_id],
                last_message=MessageSchema.model_validate(message),
            )
        )
    for message in direct_messages:
        other_id = message.recipient_id if message.sender_id == me else message.sender_id
        conversations.append(
            ConversationSchema(
                type="direct",
                user_id=other_id,
                title=names[other_id],
                last_message=MessageSchema.model_validate(message),
            )
        )

    # Newest conversation first (ids grow with time)
    conversations.sort(key=lambda c: c.last_message.id, reverse=True)
    return conversations[:limit]


@router.get("/messages", response_model=List[MessageSchema])
def get_messages(
    room_id: int | None = None,
    user_id: int | None = None,
    before: int | None = Query(None, description="Only messages older than this id"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Exactly one of room_id or user_id picks which conversation to read
    if (room_id is None) == (user_id is None):
        raise HTTPException(
            status_code=422, detail="Send either room_id or user_id, not both"
        )

    query = db.query(MessageModel)

    # Room chat: only the host and accepted players can read it
    if room_id is not None:
        room = get_room_or_404(db, room_id)
        require_room_member(db, room, current_user)
        query = query.filter(MessageModel.room_id == room_id)
    else:
        # Direct chat: only messages between the two users, in both directions.
        # Reading needs no friendship, so old history stays readable
        get_user_or_404(db, user_id)
        me = current_user.id
        query = query.filter(
            MessageModel.type == "direct",
            or_(
                (MessageModel.sender_id == me) & (MessageModel.recipient_id == user_id),
                (MessageModel.sender_id == user_id) & (MessageModel.recipient_id == me),
            ),
        )

    # Paging: only messages older than the id the client already has
    if before is not None:
        query = query.filter(MessageModel.id < before)

    # Newest first; use the smallest id of a page as `before` to get the next page
    return query.order_by(MessageModel.id.desc()).limit(limit).all()


@router.post("/messages", response_model=MessageSchema, status_code=201)
def create_message(
    message: CreateMessageSchema,
    response: Response,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Check the sender may write to this target and decide the message type
    if message.room_id is not None:
        room = get_room_or_404(db, message.room_id)
        require_room_member(db, room, current_user)
        if room.status in CLOSED_ROOM_STATUSES:
            raise HTTPException(status_code=409, detail="This room is cancelled")
        message_type = "room"
    else:
        require_can_direct_message(db, current_user, message.recipient_id)
        message_type = "direct"

    # A retried request returns the original message instead of a duplicate
    duplicate = find_duplicate(db, current_user.id, message.client_request_id)
    if duplicate:
        if not same_target(duplicate, message):
            raise HTTPException(
                status_code=409, detail="client_request_id was used for another message"
            )
        response.status_code = 200
        return duplicate

    # sender_id and type come from the server, never from the client
    new_message = MessageModel(
        sender_id=current_user.id,
        recipient_id=message.recipient_id,
        room_id=message.room_id,
        type=message_type,
        body=message.body,
        client_request_id=message.client_request_id,
    )
    db.add(new_message)
    try:
        db.commit()
    except IntegrityError:
        # Two identical requests raced: the unique constraint let only one in
        db.rollback()
        duplicate = find_duplicate(db, current_user.id, message.client_request_id)
        if duplicate and same_target(duplicate, message):
            response.status_code = 200
            return duplicate
        raise
    db.refresh(new_message)
    return new_message
