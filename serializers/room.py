from datetime import datetime, timedelta, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_extra_types.coordinate import Coordinate

from models.areas import is_area_in_district
from models.room import (
    DIFFICULTY,
    DISTRICTS,
    ROOM_ADMISSION_POLICIES,
    ROOM_VISIBILITIES,
)

# Rough bounding box around the Bahrain islands (including the Hawar Islands),
# used to reject map pins in the sea or abroad
BAHRAIN_LAT_RANGE = (25.5, 26.4)
BAHRAIN_LNG_RANGE = (50.3, 50.9)

# A room must start between 1 hour and 14 days from now
MIN_LEAD_TIME = timedelta(hours=1)
MAX_LEAD_TIME = timedelta(days=14)


def nonblank(value):
    value = value.strip()
    if not value:
        raise ValueError("cannot be blank")
    return value


NonBlank = Annotated[str, AfterValidator(nonblank)]


def _to_utc(value: datetime) -> datetime:
    # Naive datetimes are ambiguous, so they are rejected
    if value.tzinfo is None:
        raise ValueError("must include a timezone, e.g. 2026-10-10T18:00:00+03:00")
    return value.astimezone(timezone.utc)


def _check_start_window(value: datetime) -> datetime:
    # Compared against the current time when the request is parsed
    now = datetime.now(timezone.utc)
    if value < now + MIN_LEAD_TIME:
        raise ValueError("must start at least 1 hour from now")
    if value > now + MAX_LEAD_TIME:
        raise ValueError("must start within 14 days (2 weeks) from now")
    return value


def _check_choice(value: str | None, allowed: tuple, name: str):
    # None means the field was not sent (update), so it is allowed
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}")
    return value


def _check_in_bahrain(value: Coordinate | None):
    # Coordinate already checks the -90/90 and -180/180 ranges
    if value is None:
        return None
    lat_ok = BAHRAIN_LAT_RANGE[0] <= value.latitude <= BAHRAIN_LAT_RANGE[1]
    lng_ok = BAHRAIN_LNG_RANGE[0] <= value.longitude <= BAHRAIN_LNG_RANGE[1]
    if not (lat_ok and lng_ok):
        raise ValueError("venue_location must be inside Bahrain")
    return value


# Public view: the venue location and notes are left out because exact
# venue details are only for the host and admitted players
class RoomSchema(BaseModel):
    id: int
    host_id: int
    sport_id: int
    group_id: int | None = None
    title: str
    description: str | None = None
    notes: str | None = None
    difficulty: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    slot_layout: dict
    status: str
    visibility: str
    admission_policy: str
    cancellation_reason: str | None = None
    cancelled_at: datetime | None = None
    district: str
    area: str
    distance_km: float | None = None
    pace_notes: str | None = None
    route_notes: str | None = None
    host_generation: int
    revision: int
    slots_left: int = 0

    model_config = ConfigDict(from_attributes=True)


# Full view for the host (and later, accepted members)
class RoomDetailSchema(RoomSchema):
    venue_location: Coordinate | None = None
    venue_notes: str | None = None

class MyRoomsPageSchema(BaseModel):
    items: list[RoomDetailSchema]
    total: int
    limit: int
    offset: int
    has_more: bool


class JoinedMembershipSchema(BaseModel):
    status: str
    requested: bool | None = None
    position: str | None = None
    attendance: str | None = None

    model_config = ConfigDict(from_attributes=True)


class JoinedRoomSchema(RoomSchema):
    membership: JoinedMembershipSchema


class JoinedRoomDetailSchema(RoomDetailSchema):
    membership: JoinedMembershipSchema


class JoinedRoomsPageSchema(BaseModel):
    items: list[JoinedRoomDetailSchema | JoinedRoomSchema]
    total: int
    limit: int
    offset: int
    has_more: bool


# POST body: host_id, status and the counters are set by the server
class CreateRoomSchema(BaseModel):
    sport_id: int
    group_id: int | None = None
    title: NonBlank = Field(min_length=1)
    description: str | None = None
    notes: str | None = None
    difficulty: str = "beginners"
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0)
    slot_layout: dict = Field(default_factory=dict)
    visibility: str = "public"
    admission_policy: str = "approval"
    district: str
    area: NonBlank = Field(min_length=1)
    venue_location: Coordinate | None = None
    venue_notes: str | None = None
    distance_km: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    pace_notes: str | None = None
    route_notes: str | None = None

    # Convert both times to UTC (the database stores UTC)
    @field_validator("starts_at", "ends_at")
    @classmethod
    def times_in_utc(cls, value: datetime):
        return _to_utc(value)

    # Only the start is limited by the lead time window
    @field_validator("starts_at")
    @classmethod
    def start_within_window(cls, value: datetime):
        return _check_start_window(value)

    # Allowed values come from the tuples in models/room.py
    @field_validator("difficulty")
    @classmethod
    def valid_difficulty(cls, value: str):
        return _check_choice(value, DIFFICULTY, "difficulty")

    @field_validator("visibility")
    @classmethod
    def valid_visibility(cls, value: str):
        return _check_choice(value, ROOM_VISIBILITIES, "visibility")

    @field_validator("admission_policy")
    @classmethod
    def valid_admission_policy(cls, value: str):
        return _check_choice(value, ROOM_ADMISSION_POLICIES, "admission_policy")

    @field_validator("district")
    @classmethod
    def valid_district(cls, value: str):
        return _check_choice(value, DISTRICTS, "district")

    @field_validator("venue_location")
    @classmethod
    def valid_location(cls, value: Coordinate | None):
        return _check_in_bahrain(value)

    # Rules that compare several fields run after the fields are validated
    @model_validator(mode="after")
    def check_room_rules(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if not is_area_in_district(self.area, self.district):
            raise ValueError(f"area '{self.area}' is not in the {self.district} district")
        if self.visibility == "group" and self.group_id is None:
            raise ValueError("group_id is required when visibility is 'group'")
        return self


# PUT: every field is optional except revision, which must match the stored
# value so a stale edit is rejected. host_id, status and the counters are
# never accepted from the client.
class UpdateRoomSchema(BaseModel):
    revision: int
    sport_id: int | None = None
    group_id: int | None = None
    title: NonBlank | None = Field(default=None, min_length=1)
    description: str | None = None
    notes: str | None = None
    difficulty: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    capacity: int | None = Field(default=None, gt=0)
    slot_layout: dict | None = None
    visibility: str | None = None
    admission_policy: str | None = None
    district: str | None = None
    area: NonBlank | None = Field(default=None, min_length=1)
    venue_location: Coordinate | None = None
    venue_notes: str | None = None
    distance_km: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    pace_notes: str | None = None
    route_notes: str | None = None

    # Same validators as create, but a missing (None) value is skipped
    @field_validator("starts_at", "ends_at")
    @classmethod
    def times_in_utc(cls, value: datetime | None):
        return None if value is None else _to_utc(value)

    @field_validator("starts_at")
    @classmethod
    def start_within_window(cls, value: datetime | None):
        return None if value is None else _check_start_window(value)

    @field_validator("difficulty")
    @classmethod
    def valid_difficulty(cls, value: str | None):
        return _check_choice(value, DIFFICULTY, "difficulty")

    @field_validator("visibility")
    @classmethod
    def valid_visibility(cls, value: str | None):
        return _check_choice(value, ROOM_VISIBILITIES, "visibility")

    @field_validator("admission_policy")
    @classmethod
    def valid_admission_policy(cls, value: str | None):
        return _check_choice(value, ROOM_ADMISSION_POLICIES, "admission_policy")

    @field_validator("district")
    @classmethod
    def valid_district(cls, value: str | None):
        return _check_choice(value, DISTRICTS, "district")

    @field_validator("venue_location")
    @classmethod
    def valid_location(cls, value: Coordinate | None):
        return _check_in_bahrain(value)

    @model_validator(mode="after")
    def check_times(self):
        # When only one time is sent, the controller compares it with the stored one
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        # When only one of district/area is sent, the controller checks it
        # against the stored value; here only the case where both are sent
        if self.district and self.area and not is_area_in_district(self.area, self.district):
            raise ValueError(f"area '{self.area}' is not in the {self.district} district")
        return self


# Body of the cancel request; a reason is always required
class CancelRoomSchema(BaseModel):
    reason: NonBlank = Field(min_length=1)
