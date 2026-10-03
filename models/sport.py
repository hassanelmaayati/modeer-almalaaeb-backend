from sqlalchemy import JSON, Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.orm import relationship
from .base import BaseModel

# JSONB on PostgreSQL, plain JSON on SQLite (used by the tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")


class SportModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "sports"

    id = Column(Integer, primary_key=True, index=True)

    # columns of the Sports Table.
    name = Column(String, nullable=False)

    # Format presets: [{"key": "5v5", "capacity": 10}, ...]
    # Empty or missing means the sport has no fixed formats.
    formats = Column(JsonType, nullable=True)

    # Relationships to other models:
    groups = relationship("GroupModel", back_populates="sport")

    def allowed_capacities(self) -> set[int]:
        return {f["capacity"] for f in (self.formats or [])}

    def capacity_matches_format(self, capacity: int) -> bool:
        allowed = self.allowed_capacities()
        # A sport without formats accepts any capacity
        return not allowed or capacity in allowed
