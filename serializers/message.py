from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from models.message import MAX_BODY_LENGTH


# What the API returns for room chat, direct and system messages.
# sender_id is None for system messages; exactly one of room_id and
# recipient_id is set.
class MessageSchema(BaseModel):
    id: int
    sender_id: int | None = None
    recipient_id: int | None = None
    room_id: int | None = None
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

    # A message goes to a room OR to a user, never both and never neither
    @model_validator(mode="after")
    def check_target(self):
        if (self.room_id is None) == (self.recipient_id is None):
            raise ValueError("send to either room_id or recipient_id")
        return self


# One entry in the inbox: a room chat or a direct chat with one user
class ConversationSchema(BaseModel):
    type: Literal["room", "direct"]
    room_id: int | None = None  # set for room conversations
    user_id: int | None = None  # set for direct conversations (the other person)
    title: str  # room title or the other user's user_name
    last_message: MessageSchema

    @model_validator(mode="after")
    def check_target(self):
        if self.type == "room" and (self.room_id is None or self.user_id is not None):
            raise ValueError("a room conversation needs room_id and no user_id")
        if self.type == "direct" and (self.user_id is None or self.room_id is not None):
            raise ValueError("a direct conversation needs user_id and no room_id")
        return self
