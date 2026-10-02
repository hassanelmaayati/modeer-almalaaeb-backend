from pydantic import BaseModel
from typing import Optional, List
from .comment import CommentSchema
from .user import UserSchema


class TeaSchema(BaseModel):
    id: Optional[int] = True
    name: str
    in_stock: bool
    rating: int
    comments: List[CommentSchema] = []
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
