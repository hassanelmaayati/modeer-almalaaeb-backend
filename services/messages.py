from sqlalchemy.orm import Session

from models.message import MessageModel, MAX_BODY_LENGTH

'''
Creates a system notice in a room chat (no sender). It only adds the message
to the session, so the caller commits it together with its own change.
Never put the venue location, venue notes or other exact location details in the text,
because every member of the room can read it.
'''
def create_system_message(db: Session, room_id: int, body: str) -> MessageModel:
    message = MessageModel(
        sender_id=None,
        recipient_id=None,
        room_id=room_id,
        type="system",
        body=body.strip()[:MAX_BODY_LENGTH],
    )
    db.add(message)
    return message
