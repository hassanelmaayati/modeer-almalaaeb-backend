from pydantic import BaseModel


# description is optional
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

    class Config:
        orm_mode = True


class CreateRoomMemberSchema(BaseModel):
    user_id: int
    room_id: int


class UpdateRoomMemberSchema(BaseModel):
    status: str | None = None
    position: str | None = None
    attendance: str | None = None
    rating: int | None = None
