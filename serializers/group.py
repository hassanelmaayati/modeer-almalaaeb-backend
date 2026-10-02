from pydantic import BaseModel


# description is optional
class GroupSchema(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str | None = None
    photo_url: str | None = None
    sports_id: int

    class Config:
        orm_mode = True


class CreateGroupSchema(BaseModel):
    name: str
    description: str | None = None
    photo_url: str | None = None
    sports_id: int


class UpdateGroupSchema(BaseModel):
    name: str
    description: str | None = None
    photo_url: str | None = None
