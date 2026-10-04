from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from models.message import MAX_BODY_LENGTH


# sender_id is None for system messages; exactly one chat target is set.
class MessageSchema(BaseModel):
    id: int
    sender_id: int | None = None
    recipient_id: int | None = None
    room_id: int | None = None
    group_id: int | None = None
    type: str
    body: str
    client_request_id: UUID | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# POST body. sender_id, type and created_at are set by the server, so any
# of them sent by the client are ignored. System messages cannot be created
# through the API.
class CreateMessageSchema(BaseModel):
    room_id: int | None = None
    recipient_id: int | None = None
    group_id: int | None = None
    body: str
    # Lets the server return the same message when a request is retried
    client_request_id: UUID

    # Trim first, so empty spaces counts as empty and the length is measured on the text
    @field_validator("body")
    @classmethod
    def valid_body(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("body cannot be empty")
        if len(value) > MAX_BODY_LENGTH:
            raise ValueError(f"body cannot be longer than {MAX_BODY_LENGTH} characters")
        return value

    # Exactly one room, group or direct recipient.
    @model_validator(mode="after")
    def check_target(self):
        if sum(value is not None for value in (self.room_id, self.recipient_id, self.group_id)) != 1:
            raise ValueError("send to exactly one of room_id, recipient_id or group_id")
        return self


# One inbox entry, including authorized empty chats when requested.
class ConversationSchema(BaseModel):
    type: Literal["room", "direct", "group"]
    room_id: int | None = None  # set for room conversations
    user_id: int | None = None  # set for direct conversations (the other person)
    group_id: int | None = None
    title: str
    last_message: MessageSchema | None = None

    @model_validator(mode="after")
    def check_target(self):
        targets = {"room": self.room_id, "direct": self.user_id, "group": self.group_id}
        if targets[self.type] is None or sum(value is not None for value in targets.values()) != 1:
            raise ValueError("a conversation needs exactly one matching target")
        return self
