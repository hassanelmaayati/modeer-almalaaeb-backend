from pydantic import BaseModel


class GroupSchema(BaseModel):
    id: int
    owner_id: int
    name: str
    description: str
    photo_url: str
    sports_id: int

    class Config:
        orm_mode = True


class CreateGroupSchema(BaseModel):
    name: str
    description: str
    photo_url: str
    sports_id: int


class UpdateGroupSchema(BaseModel):
    name: str
    description: str
    photo_url: str
