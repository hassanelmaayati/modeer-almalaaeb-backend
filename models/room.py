from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel
from .districts import DISTRICTS  
from .group import GroupModel
from .sport import SportModel
from .user import UserModel

# JSONB on PostgreSQL, plain JSON on SQLite (used by the tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")

'''
tuples listing the allowed values for status, visibility, admission_policy, and difficulty
They're meant for serializer validation later
'''
ROOM_STATUSES = ("open", "started", "completed", "cancelled")
ROOM_VISIBILITIES = ("public", "private", "group")
ROOM_ADMISSION_POLICIES = ("approval", "open")
DIFFICULTY = ("beginners", "medium", "advanced")

class RoomModel(BaseModel):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)

    # owner, groups, and sport
    host_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sport_id = Column(Integer, ForeignKey("sports.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)

    # room details
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    difficulty = Column(String, nullable=False, default="beginners", server_default="beginners")

    # Schedule (stored in UTC, shown in Bahrain time)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)

    # Capacity, slot_layout holds team positions or pool places as JSON
    capacity = Column(Integer, nullable=False)
    slot_layout = Column(JsonType, nullable=False, default=dict)

    # Lifecycle and access
    status = Column(String, nullable=False, default="open", server_default="open")
    visibility = Column(String, nullable=False, default="public", server_default="public")
    admission_policy = Column(String, nullable=False, default="approval", server_default="approval")

    # District is the Bahrain governorate used to find rooms near the user
    district = Column(String, nullable=False)

    # Area (a place inside the district) is safe to show. The venue location
    # (map pin as latitude/longitude, both set or both empty) and the venue
    # notes are for the host and admitted players only
    area = Column(String, nullable=False)
    venue_latitude = Column(Float, nullable=True)
    venue_longitude = Column(Float, nullable=True)
    venue_notes = Column(Text, nullable=True)

    # Optional walking, running and cycling details
    distance_km = Column(Float, nullable=True)
    pace_notes = Column(String, nullable=True)
    route_notes = Column(Text, nullable=True)

    # Reject stale host commands and concurrent edits
    host_generation = Column(Integer, nullable=False, default=0, server_default="0")
    revision = Column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_rooms_end_after_start"),
        CheckConstraint("capacity > 0", name="ck_rooms_capacity_positive"),
        CheckConstraint(
            "status IN ('open', 'started', 'completed', 'cancelled')",
            name="ck_rooms_status",
        ),
        CheckConstraint(
            "visibility IN ('public', 'private', 'group')",
            name="ck_rooms_visibility",
        ),
        CheckConstraint(
            "admission_policy IN ('approval', 'open')",
            name="ck_rooms_admission_policy",
        ),
        CheckConstraint(
            "difficulty IN ('beginners', 'medium', 'advanced')",
                name="ck_rooms_difficulty",
            ),
        CheckConstraint(
            "district IN ('capital', 'muharraq', 'northern', 'southern')",
            name="ck_rooms_district",
        ),
        CheckConstraint(
            "visibility != 'group' OR group_id IS NOT NULL",
            name="ck_rooms_group_visibility_needs_group",
        ),
        CheckConstraint(
            "venue_latitude BETWEEN -90 AND 90",
            name="ck_rooms_venue_latitude_range",
        ),
        CheckConstraint(
            "venue_longitude BETWEEN -180 AND 180",
            name="ck_rooms_venue_longitude_range",
        ),
        CheckConstraint(
            "(venue_latitude IS NULL) = (venue_longitude IS NULL)",
            name="ck_rooms_venue_location_both_or_none",
        ),
        # Matches the discovery query: district, open status, upcoming start
        Index("ix_rooms_district_status_starts_at", "district", "status", "starts_at"),
    )

    # Relationships to other models:
    host = relationship(
        "UserModel", foreign_keys=[host_id], back_populates="hosted_rooms"
    )
    sport = relationship("SportModel", back_populates="rooms")
    group = relationship("GroupModel", back_populates="rooms")
    memberships = relationship("MembershipModel", back_populates="room")
    messages = relationship("MessageModel", back_populates="room")

    def validate_capacity(self):
        """Raise ValueError if capacity does not match one of the sport's formats"""
        if self.sport is None:
            return
        if not self.sport.capacity_matches_format(self.capacity):
            allowed = sorted(self.sport.allowed_capacities())
            raise ValueError(
                f"capacity {self.capacity} does not match any {self.sport.name} "
                f"format (allowed: {allowed})"
            )
