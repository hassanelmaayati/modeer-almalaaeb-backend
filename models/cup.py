from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .base import BaseModel

# JSONB on PostgreSQL, plain JSON on SQLite for the tests
JSON_DATA = JSON().with_variant(JSONB(), "postgresql")

# Cup format per sport, keyed by lowercase sport name because the sports table
# has no slug. Kept here rather than as a column so Ahmed's sports table is
# unchanged; a sport missing from this map cannot host cups yet.
CUP_FORMATS = {
    # Head-to-head sports: two sides meet and one goes through, so a bracket
    "football": "knockout",
    "basketball": "knockout",
    "volleyball": "knockout",
    "tennis": "knockout",
    "padel": "knockout",
    "handball": "knockout",
    "badminton": "knockout",
    "billiards": "knockout",
    # Timed sports: everyone starts together and is ranked by finishing time
    "running": "race",
    "marathon": "race",
    "cycling": "race",
    "kayak": "race",
    "kayaking": "race",
    "swimming": "race",
}

# Sports that deliberately have no cups, with the reason shown to the user
NO_CUP_SPORTS = {
    "walking": "Walking is a social outing, not a competition, so it has no cups",
}


class CupModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "cups"
    __table_args__ = (
        # Only knockout needs 4, 8 or 16 (a bracket halves every round); races
        # take any field size, so the per-format rule lives in the controller
        CheckConstraint("team_count >= 2", name="ck_cups_team_count"),
        CheckConstraint("roster_limit > 0", name="ck_cups_roster_limit"),
        CheckConstraint(
            "status IN ('draft', 'registration', 'published', 'completed')",
            name="ck_cups_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # columns of the Cups Table.
    organizer_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sport_id = Column(Integer, ForeignKey("sports.id"), nullable=False)
    name = Column(String, nullable=False)
    rules = Column(Text, nullable=False)
    # Knockout: number of teams in the bracket. Race: maximum number of entrants
    team_count = Column(Integer, nullable=False)
    roster_limit = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="draft", server_default="draft")

    # Stored as UTC without a timezone, like created_at
    registration_closes_at = Column(DateTime, nullable=True)
    rosters_locked_at = Column(DateTime, nullable=True)

    # Entrant snapshots (plus race results) and the knockout bracket,
    # validated by the controller
    entries = Column(JSON_DATA, nullable=False, default=list)
    fixtures = Column(JSON_DATA, nullable=False, default=list)

    # Bumped on every change so stale edits can be rejected
    revision = Column(Integer, nullable=False, default=0, server_default="0")

    # Relationships to other models:
    organizer = relationship("UserModel", back_populates="organized_cups")
    sport = relationship("SportModel")
    memberships = relationship("MembershipModel", back_populates="cup")

    @property
    def format(self):
        return CUP_FORMATS.get(self.sport.name.strip().lower())
