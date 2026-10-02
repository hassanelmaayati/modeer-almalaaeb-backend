from pydantic import BaseModel


# Form Schema
class UserRegistrationSchema(BaseModel):
    username: str
    email: str
    password: str


class UserLoginSchema(BaseModel):
    username: str
    password: str


# Response Schema
class UserSchema(BaseModel):
    username: str
    email: str

    class Config:
        orm_mode = True


class UserTokenSchema(BaseModel):
    token: str
    msg: str
