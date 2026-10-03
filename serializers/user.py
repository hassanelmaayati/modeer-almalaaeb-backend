from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

HANDLE_PATTERN = r"^[a-z0-9_]{3,30}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# Form Schemas
class UserSignupSchema(BaseModel):
    display_name: str = Field(min_length=1, max_length=60)
    handle: str = Field(pattern=HANDLE_PATTERN)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8)

    @field_validator("handle", "email", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserLoginSchema(BaseModel):
    # Accepts either the email or the handle
    identifier: str
    password: str


class UserUpdateSchema(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    handle: str | None = Field(default=None, pattern=HANDLE_PATTERN)
    avatar_url: str | None = None
    bio: str | None = Field(default=None, max_length=500)

    @field_validator("handle", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


# Response Schemas
class UserSchema(BaseModel):
    # Safe public profile; never exposes login fields
    id: int
    display_name: str
    handle: str
    avatar_url: str | None = None
    bio: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class UserPrivateSchema(UserSchema):
    # Only returned to the user themselves
    email: str | None = None
    has_password: bool
    google_linked: bool


class UserTokenSchema(BaseModel):
    token: str
    msg: str
    user: UserPrivateSchema
