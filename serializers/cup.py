from datetime import datetime, timezone
from typing import Annotated, List, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .user import UserSchema


def to_naive_utc(value: datetime) -> datetime:
    # The database stores UTC without a timezone, like created_at
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def to_aware_utc(value: datetime) -> datetime:
    # Responses always say they are UTC so the frontend can show Bahrain time
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UtcInput = Annotated[datetime, AfterValidator(to_naive_utc)]
UtcOutput = Annotated[datetime, AfterValidator(to_aware_utc)]


# Response Schemas
class CupEntrySchema(BaseModel):
    group_id: int
    group_name: str
    owner_user_id: int
    status: Literal["pending", "accepted", "declined", "withdrawn"]
    entered_at: UtcOutput
    # Race cups only; knockout results live in the fixtures instead
    finish_time_seconds: float | None = None
    position: int | None = None
    did_not_finish: bool = False


class CupFixtureSchema(BaseModel):
    id: str
    round: int
    match: int
    home_group_id: int | None = None
    away_group_id: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    winner_group_id: int | None = None


class CupSchema(BaseModel):
    id: int
    organizer_user_id: int
    organizer: UserSchema
    sport_id: int
    # "knockout" or "race", worked out from the sport
    format: str | None = None
    name: str
    rules: str
    team_count: int
    roster_limit: int
    status: str
    registration_closes_at: UtcOutput | None = None
    rosters_locked_at: UtcOutput | None = None
    entries: List[CupEntrySchema] = []
    fixtures: List[CupFixtureSchema] = []
    revision: int
    created_at: UtcOutput | None = None

    model_config = ConfigDict(from_attributes=True)


# Form Schemas
class CreateCupSchema(BaseModel):
    sport_id: int
    name: str = Field(min_length=1, max_length=100)
    rules: str = Field(min_length=1)
    # 4, 8 or 16 is enforced for knockout cups in the controller
    team_count: int = Field(ge=2, le=100)
    roster_limit: int = Field(gt=0)
    registration_closes_at: UtcInput | None = None


class FixtureResultSchema(BaseModel):
    fixture_id: str
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    # Required when the scores are level (decided on penalties)
    winner_group_id: int | None = None


class RaceResultSchema(BaseModel):
    group_id: int
    finish_time_seconds: float | None = Field(default=None, gt=0)
    position: int | None = Field(default=None, ge=1)
    did_not_finish: bool = False

    @model_validator(mode="after")
    def one_result(self):
        # Each entrant gets exactly one outcome: a time, a position, or a DNF
        given = [
            self.finish_time_seconds is not None,
            self.position is not None,
            self.did_not_finish,
        ]
        if sum(given) != 1:
            raise ValueError(
                "Give exactly one of finish_time_seconds, position or did_not_finish"
            )
        return self


class UpdateCupSchema(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rules: str | None = Field(default=None, min_length=1)
    team_count: int | None = Field(default=None, ge=2, le=100)
    roster_limit: int | None = Field(default=None, gt=0)
    registration_closes_at: UtcInput | None = None
    # Completion happens automatically once all results are recorded
    status: Literal["registration", "published"] | None = None
    # Knockout cups send one fixture result; race cups send finishing results
    result: FixtureResultSchema | None = None
    race_results: List[RaceResultSchema] | None = Field(default=None, min_length=1)
    revision: int | None = None


class CreateEntrySchema(BaseModel):
    group_id: int
    revision: int | None = None


class UpdateEntrySchema(BaseModel):
    status: Literal["accepted", "declined", "withdrawn"]
    revision: int | None = None
