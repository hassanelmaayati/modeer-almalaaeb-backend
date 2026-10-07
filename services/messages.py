from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from models.base import utc_now
from models.group import GroupModel
from models.message import MessageModel, MAX_BODY_LENGTH
from models.room import RoomModel
from serializers.message import CreateMessageSchema, MessageSchema
from services.chat_access import group_user_ids, require_chat_access, require_direct_send, room_user_ids
from services.memberships import load
from services.notifications import notify_users
from services.realtime import user_event


def message_events(db: Session, message: MessageModel, event_type: str = "message.created") -> list[dict]:
    """Snapshot chat data for after-commit delivery; notifications are handled separately.

    Edits and deletes use the same audience as the original message."""
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
    payload = {"type": event_type, "message": MessageSchema.model_validate(message).model_dump(mode="json")}
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


def create_system_message(db: Session, room_id: int, body: str) -> MessageModel:
    """Add a notice to the caller's transaction; never include the exact venue location or notes."""
    message = MessageModel(room_id=room_id, type="system", body=body.strip()[:MAX_BODY_LENGTH])
    db.add(message)
    return message


# What a deleted message's row keeps instead of the text (the body column cannot be blank)
DELETED_BODY = "[deleted]"


def require_can_send(db: Session, user, message: MessageModel):
    """The same checks as sending, so editing is refused wherever sending would be."""
    if message.room_id is not None:
        room = load(db, RoomModel, message.room_id, lock=True)
        require_chat_access(db, user.id, {"type": "room", "id": message.room_id})
        if room.status == "cancelled":
            raise HTTPException(status_code=409, detail="This room is cancelled")
    elif message.group_id is not None:
        load(db, GroupModel, message.group_id, lock=True)
        require_chat_access(db, user.id, {"type": "group", "id": message.group_id})
    else:
        require_direct_send(db, user.id, message.recipient_id)


def load_own_message(db: Session, user, message_id: int) -> MessageModel:
    message = db.get(MessageModel, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.type == "system":
        # Only people who can read the room learn that the notice exists
        require_chat_access(db, user.id, {"type": "room", "id": message.room_id})
        raise HTTPException(status_code=403, detail="System messages cannot be changed")
    if message.sender_id != user.id:
        # Other people's messages look missing, so ids cannot be probed
        raise HTTPException(status_code=404, detail="Message not found")
    # Chat locks are taken first (as when sending), then the message row
    require_can_send(db, user, message)
    return db.query(MessageModel).filter(MessageModel.id == message_id).with_for_update().populate_existing().one()


def edit_message(db: Session, user, message_id: int, body: str):
    message = load_own_message(db, user, message_id)
    if message.deleted_at is not None:
        raise HTTPException(status_code=409, detail="This message was deleted")
    if body == message.body:
        return message, []
    message.body, message.edited_at = body, utc_now()
    events = message_events(db, message, "message.updated")
    db.commit()
    db.refresh(message)
    return message, events


def delete_message(db: Session, user, message_id: int):
    message = load_own_message(db, user, message_id)
    if message.deleted_at is not None:
        return message, []
    # The text is erased, not just hidden, so it cannot come back out of the database
    message.body, message.deleted_at = DELETED_BODY, utc_now()
    events = message_events(db, message, "message.deleted")
    db.commit()
    db.refresh(message)
    return message, events
