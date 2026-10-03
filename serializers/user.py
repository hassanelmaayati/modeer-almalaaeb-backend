from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# Response Schemas
class UserSchema(BaseModel):
    # Safe public profile; never exposes login fields
    id: int
    user_name: str
    photo_url: str | None = None
    bio: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserTokenSchema(BaseModel):
    token: str
    msg: str
    user: UserSchema


# Form Schemas
class UserSignupSchema(BaseModel):
    user_name: str = Field(min_length=3, max_length=60)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8)
    photo_url: str | None = None
    bio: str | None = Field(default=None, max_length=500)

    @field_validator("user_name", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserLoginSchema(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserUpdateSchema(BaseModel):
    user_name: str = Field(min_length=3, max_length=60)
    photo_url: str | None = None
    bio: str | None = Field(default=None, max_length=500)

    @field_validator("user_name", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip() if isinstance(value, str) else value
