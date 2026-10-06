from pydantic import BaseModel, Field


# Response Schemas
class PlayerRatingSchema(BaseModel):
    # The player who was rated; the rater is always the caller, so it is never shown
    user_id: int
    stars: int


class UserRatingSchema(BaseModel):
    user_id: int
    # One decimal, or null while nobody has rated this user
    average_rating: float | None = None
    rating_count: int


# Form Schemas
class CreatePlayerRatingSchema(BaseModel):
    user_id: int
    # Strict: only whole JSON numbers, so "4", 4.5 and true are rejected
    stars: int = Field(strict=True, ge=1, le=5)
