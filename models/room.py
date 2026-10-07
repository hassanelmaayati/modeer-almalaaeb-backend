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
from geoalchemy2 import Geography
from geoalchemy2.shape import to_shape
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel
from .districts import DISTRICTS  
from .group import GroupModel
from .sport import SportModel
from .user import UserModel

# JSONB on PostgreSQL, plain JSON on SQLite (used by the tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")

# PostGIS geography point (distances are in metres) on PostgreSQL
# plain text on SQLite (used by the tests, which have no PostGIS)
PointType = Geography(geometry_type="POINT", srid=4326, spatial_index=False).with_variant(
    Text(), "sqlite"
)


def make_point(latitude: float, longitude: float) -> str:
    """Point as EWKT, which PostGIS reads directly and SQLite stores as text"""
    # PostGIS wants longitude first
    return f"SRID=4326;POINT({longitude} {latitude})"

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
    # General notes for everyone who can see the room (the private venue notes are separate)
    notes = Column(Text, nullable=True)
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
    cancellation_reason = Column(Text, nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # District is the Bahrain governorate used to find rooms near the user
    district = Column(String, nullable=False)

    # location details 
    area = Column(String, nullable=False)
    venue_point = Column(PointType, nullable=True)
    venue_notes = Column(Text, nullable=True)

    # Optional walking, running and cycling details
    distance_km = Column(Float, nullable=True)
    pace_notes = Column(String, nullable=True)
    route_notes = Column(Text, nullable=True)

    # Reject stale host commands and concurrent edits
    host_generation = Column(Integer, nullable=False, default=0, server_default="0")
    # Since when a started room has had no connected host (UTC); cleared when they return
    host_away_since = Column(DateTime, nullable=True)
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
        # Matches the discovery query: district, open status, upcoming start
        Index("ix_rooms_district_status_starts_at", "district", "status", "starts_at"),
        # Matches the host's own room list: one host, ordered or filtered by start time
        Index("ix_rooms_host_id_starts_at", "host_id", "starts_at"),
        # Group room lists
        Index("ix_rooms_group_id", "group_id"),
        # Spatial index for distance queries (ignored on SQLite)
        Index("ix_rooms_venue_point", "venue_point", postgresql_using="gist"),
    )

    # Relationships to other models:
    host = relationship(
        "UserModel", foreign_keys=[host_id], back_populates="hosted_rooms"
    )
    sport = relationship("SportModel", back_populates="rooms")
    group = relationship("GroupModel", back_populates="rooms")
    memberships = relationship("MembershipModel", back_populates="room")
    messages = relationship("MessageModel", back_populates="room")

    @property
    def venue_location(self):
        """Map pin as {"latitude", "longitude"}, or None when no pin was set"""
        point = self.venue_point
        if point is None:
            return None
        if isinstance(point, str):
            longitude, latitude = map(float, point.split("POINT(")[1].rstrip(")").split())
        else:
            # PostgreSQL returns a WKB element
            shape = to_shape(point)
            longitude, latitude = shape.x, shape.y
        return {"latitude": latitude, "longitude": longitude}

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
