from pydantic import BaseModel, ConfigDict, Field, field_validator


class GroupFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    photo_url: str | None = None

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

    model_config = ConfigDict(from_attributes=True)


class CreateGroupSchema(GroupFields):
    sports_id: int


class UpdateGroupSchema(GroupFields):
    pass
