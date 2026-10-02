from pydantic import BaseModel


class SportSchema(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True
