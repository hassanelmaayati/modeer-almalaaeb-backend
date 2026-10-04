from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models.group import GroupModel
from models.message import MessageModel, MAX_BODY_LENGTH
from models.room import RoomModel
from serializers.message import CreateMessageSchema, MessageSchema
from services.chat_access import group_user_ids, require_chat_access, require_direct_send, room_user_ids
from services.memberships import load
from services.notifications import notify_users
from services.realtime import user_event


def message_events(db: Session, message: MessageModel) -> list[dict]:
    """Snapshot chat data for after-commit delivery; notifications are handled separately."""
    if message.id is None:
        db.flush()
    if message.room_id is not None:
        target = {"type": "room", "id": message.room_id}
        recipients = room_user_ids(db, message.room_id)
    elif message.group_id is not None:
        target = {"type": "group", "id": message.group_id}
        recipients = group_user_ids(db, message.group_id)
    else:
        target = None
        recipients = {message.sender_id, message.recipient_id}
    payload = {"type": "message.created", "message": MessageSchema.model_validate(message).model_dump(mode="json")}
    return [user_event(recipients, payload, scope=target)]


def same_target(message: MessageModel, data: CreateMessageSchema) -> bool:
    return (message.room_id, message.recipient_id, message.group_id) == (data.room_id, data.recipient_id, data.group_id)


def find_duplicate(db: Session, sender_id: int, request_id):
    return db.query(MessageModel).filter(MessageModel.sender_id == sender_id, MessageModel.client_request_id == request_id).first()


def save_message(db: Session, user, data: CreateMessageSchema):
    """Save a chat message and incoming alerts once, in the same transaction."""
    if data.room_id is not None:
        room = load(db, RoomModel, data.room_id, lock=True)
        target = {"type": "room", "id": data.room_id}
        require_chat_access(db, user.id, target)
        if room.status == "cancelled":
            raise HTTPException(status_code=409, detail="This room is cancelled")
        kind = "room"
    elif data.group_id is not None:
        load(db, GroupModel, data.group_id, lock=True)
        target = {"type": "group", "id": data.group_id}
        require_chat_access(db, user.id, target)
        kind = "group"
    else:
        require_direct_send(db, user.id, data.recipient_id)
        target = {"type": "direct", "id": user.id}
        kind = "direct"

    duplicate = find_duplicate(db, user.id, data.client_request_id)
    if duplicate:
        if not same_target(duplicate, data):
            raise HTTPException(status_code=409, detail="client_request_id was used for another message")
        return duplicate, False, []

    message = MessageModel(**data.model_dump(), sender_id=user.id, type=kind)
    db.add(message)
    try:
        db.flush()
        events = message_events(db, message)
        events += notify_users(db, events[0]["user_ids"], f"message.{kind}", target, f"New message from {user.user_name}", exclude_user_id=user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = find_duplicate(db, user.id, data.client_request_id)
        if duplicate and same_target(duplicate, data):
            return duplicate, False, []
        raise HTTPException(status_code=409, detail="This message conflicts with existing data")
    db.refresh(message)
    return message, True, events


'''
Creates a system notice in a room chat (no sender). It only adds the message
to the session, so the caller commits it together with its own change.
Never put the venue location, venue notes or other exact location details in the text,
because every member of the room can read it.
'''
def create_system_message(db: Session, room_id: int, body: str) -> MessageModel:
    """Add a notice to the caller's transaction; never include an exact venue."""
    message = MessageModel(room_id=room_id, type="system", body=body.strip()[:MAX_BODY_LENGTH])
    db.add(message)
    return message
