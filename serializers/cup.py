from datetime import datetime, timezone
from typing import Annotated, List, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from .fields import Id
from .times import UtcOutput
from .user import UserSchema


def to_naive_utc(value: datetime) -> datetime:
    # The database stores UTC without a timezone, like created_at
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


UtcInput = Annotated[datetime, AfterValidator(to_naive_utc)]


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
class CupTextFields(BaseModel):
    @field_validator('name', 'rules', mode='before', check_fields=False)
    @classmethod
    def normalize_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class CreateCupSchema(CupTextFields):
    sport_id: Id
    name: str = Field(min_length=1, max_length=100)
    rules: str = Field(min_length=1, max_length=5000)
    # 4, 8 or 16 is enforced for knockout cups in the controller
    team_count: int = Field(ge=2, le=100)
    roster_limit: int = Field(gt=0, le=100)
    registration_closes_at: UtcInput | None = None


class FixtureResultSchema(BaseModel):
    fixture_id: str
    home_score: int = Field(ge=0, le=1000)
    away_score: int = Field(ge=0, le=1000)
    # Required when the scores are level (decided on penalties)
    winner_group_id: Id | None = None


class RaceResultSchema(BaseModel):
    group_id: Id
    finish_time_seconds: float | None = Field(default=None, gt=0, le=10_000_000, allow_inf_nan=False)
    position: int | None = Field(default=None, ge=1, le=10_000)
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


class UpdateCupSchema(CupTextFields):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rules: str | None = Field(default=None, min_length=1, max_length=5000)
    team_count: int | None = Field(default=None, ge=2, le=100)
    roster_limit: int | None = Field(default=None, gt=0, le=100)
    registration_closes_at: UtcInput | None = None
    # Completion happens automatically once all results are recorded
    status: Literal["registration", "published"] | None = None
    # Knockout cups send one fixture result; race cups send finishing results
    result: FixtureResultSchema | None = None
    race_results: List[RaceResultSchema] | None = Field(default=None, min_length=1)
    # Required so a stale client gets 409 instead of overwriting newer changes
    revision: int


class CreateEntrySchema(BaseModel):
    group_id: Id
    revision: int


class UpdateEntrySchema(BaseModel):
    status: Literal["accepted", "declined", "withdrawn"]
    revision: int
