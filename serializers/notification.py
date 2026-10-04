from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class NotificationTargetSchema(BaseModel):
    type: Literal["room", "group", "direct", "cup"]
    id: int = Field(gt=0)


class NotificationSchema(BaseModel):
    id: int
    kind: str
    target: NotificationTargetSchema
    text: str
    read_at: datetime | None = None
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("read_at", "created_at")
    @classmethod
    def utc_time(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


class NotificationListSchema(BaseModel):
    items: list[NotificationSchema]
    unread_count: int


class ReadNotificationsSchema(BaseModel):
    read: Literal[True]
