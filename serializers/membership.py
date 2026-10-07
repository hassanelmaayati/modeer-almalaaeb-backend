from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .fields import Id


class RoomMemberSchema(BaseModel):
    id: int
    user_id: int
    room_id: int
    status: str
    requested: bool | None = None
    accepted: bool | None = None
    position: str | None = None
    attendance: str | None = None
    rating: int | None = None

    model_config = ConfigDict(from_attributes=True)


class CreateRoomMemberSchema(BaseModel):
    user_id: Id | None = None


class UpdateRoomMemberSchema(BaseModel):
    status: Literal["pending", "accepted", "declined", "left", "removed"] | None = None
    position: str | None = Field(default=None, max_length=50)
    attendance: Literal["unknown", "present", "no_show", "excused"] | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class MemberSchema(BaseModel):
    id: int
    user_id: int
    room_id: int | None = None
    group_id: int | None = None
    cup_id: int | None = None
    other_user_id: int | None = None
    status: str
    requested: bool | None = None
    accepted: bool | None = None
    position: str | None = None
    attendance: str | None = None
    rating: int | None = None
    user_blocked_other: str | None = None
    other_blocked_user: str | None = None

    model_config = ConfigDict(from_attributes=True)


class FriendSchema(MemberSchema):
    pass


class CreateFriendSchema(BaseModel):
    other_user_id: Id


class UpdateFriendSchema(BaseModel):
    status: str | None = None
    user_blocked_other: str | None = None
    other_blocked_user: str | None = None


class GroupMemberSchema(MemberSchema):
    pass


class CreateGroupMemberSchema(BaseModel):
    user_id: Id


class UpdateGroupMemberSchema(BaseModel):
    status: str | None = None


class CupMemberSchema(MemberSchema):
    pass


class CreateCupMemberSchema(BaseModel):
    user_id: Id
    group_id: Id


class UpdateCupMemberSchema(BaseModel):
    status: str | None = None
