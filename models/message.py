from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import relationship

from .base import BaseModel
from .room import RoomModel
from .user import UserModel

# Allowed values for type, used by the serializers later
MESSAGE_TYPES = ("room", "direct", "group", "system")
MAX_BODY_LENGTH = 2000


class MessageModel(BaseModel):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)

    # A room, group or direct recipient; system messages have no sender.
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", name="fk_messages_group_id_groups"), nullable=True)

    # room, group, direct or system
    type = Column(String, nullable=False)
    body = Column(Text, nullable=False)

    # Sent by the client, so a retried request does not create a duplicate
    client_request_id = Column(Uuid, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('room', 'direct', 'group', 'system')",
            name="ck_messages_type",
        ),
        # Exactly one target.
        CheckConstraint(
            "(room_id IS NOT NULL AND recipient_id IS NULL AND group_id IS NULL) "
            "OR (room_id IS NULL AND recipient_id IS NOT NULL AND group_id IS NULL) "
            "OR (room_id IS NULL AND recipient_id IS NULL AND group_id IS NOT NULL)",
            name="ck_messages_exactly_one_target",
        ),
        # The type must agree with the target and the sender
        CheckConstraint(
            "(type = 'room' AND room_id IS NOT NULL AND sender_id IS NOT NULL) "
            "OR (type = 'direct' AND recipient_id IS NOT NULL AND sender_id IS NOT NULL) "
            "OR (type = 'group' AND group_id IS NOT NULL AND sender_id IS NOT NULL) "
            "OR (type = 'system' AND room_id IS NOT NULL AND sender_id IS NULL)",
            name="ck_messages_type_matches_target",
        ),
        # No self messaging
        CheckConstraint(
            "recipient_id IS NULL OR sender_id != recipient_id",
            name="ck_messages_no_self_message",
        ),
        # No empty messages
        CheckConstraint("length(trim(body)) > 0", name="ck_messages_body_not_blank"),
        # NULL values are ignored, so system messages need no request id
        UniqueConstraint(
            "sender_id", "client_request_id", name="uq_messages_sender_request"
        ),
        Index("ix_messages_room_created", "room_id", "created_at"),
        Index("ix_messages_group_created", "group_id", "created_at"),
        Index("ix_messages_recipient_created", "recipient_id", "created_at"),
    )

    # Relationships to other models:
    sender = relationship(
        "UserModel", foreign_keys=[sender_id], back_populates="sent_messages"
    )
    recipient = relationship(
        "UserModel", foreign_keys=[recipient_id], back_populates="received_messages"
    )
    room = relationship("RoomModel", back_populates="messages")
    group = relationship("GroupModel")
