from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .fields import Id, PhotoUrl


class GroupFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    photo_url: PhotoUrl = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("name cannot be blank")
        return value.strip()


# description is optional
class GroupSchema(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None = None
    photo_url: str | None = None
    sports_id: int
    # People in the group: the owner plus accepted members
    member_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class GroupMineSchema(GroupSchema):
    role: Literal["owner", "member"]


class CreateGroupSchema(GroupFields):
    sports_id: Id


class UpdateGroupSchema(GroupFields):
    pass
