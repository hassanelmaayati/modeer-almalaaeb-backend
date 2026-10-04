from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.districts import DISTRICTS

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _check_district(value: str | None):
    # None means no home district (not picked, or cleared)
    if value is not None and value not in DISTRICTS:
        raise ValueError(f"district must be one of: {', '.join(DISTRICTS)}")
    return value


# Response Schemas
class UserSchema(BaseModel):
    # Safe public profile; never exposes login fields
    id: int
    user_name: str
    photo_url: str | None = None
    bio: str | None = None
    district: str | None = None
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
    district: str | None = None

    @field_validator("user_name", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("district")
    @classmethod
    def valid_district(cls, value: str | None):
        return _check_district(value)

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
    district: str | None = None

    @field_validator("district")
    @classmethod
    def valid_district(cls, value: str | None):
        return _check_district(value)

    @field_validator("user_name", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip() if isinstance(value, str) else value
