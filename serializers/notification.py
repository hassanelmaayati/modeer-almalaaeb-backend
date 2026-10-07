from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .times import UtcOutput


class NotificationTargetSchema(BaseModel):
    type: Literal["room", "group", "direct", "cup"]
    id: int = Field(gt=0)


class NotificationSchema(BaseModel):
    id: int
    kind: str
    target: NotificationTargetSchema
    text: str
    read_at: UtcOutput | None = None
    created_at: UtcOutput | None = None
    model_config = ConfigDict(from_attributes=True)


class NotificationListSchema(BaseModel):
    items: list[NotificationSchema]
    unread_count: int


class ReadNotificationsSchema(BaseModel):
    read: Literal[True]
