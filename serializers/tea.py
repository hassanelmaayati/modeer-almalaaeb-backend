from pydantic import BaseModel
from typing import Optional, List
from .group import GroupSchema
from .user import UserSchema


class TeaSchema(BaseModel):
    id: Optional[int] = True
    name: str
    in_stock: bool
    rating: int
    groups: List[GroupSchema] = []
    user: UserSchema

    class Config:
        orm_mode = True


# these are for req.body
class CreateTeaSchema(BaseModel):
    name: str
    in_stock: bool
    rating: int

    class Config:
        orm_mode = True


class UpdateTeaSchema(BaseModel):
    name: str
    in_stock: bool
    rating: int

    class Config:
        orm_mode = True
