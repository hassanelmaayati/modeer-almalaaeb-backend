# models/base.py
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy.orm import declarative_base

# Create a base class for all models
Base = declarative_base()


def utc_now() -> datetime:
    # Naive UTC, like the other timestamps. The database's now() uses the server's
    # timezone, which is not always UTC, so the application sets the time itself.
    return datetime.now(timezone.utc).replace(tzinfo=None)


class BaseModel(Base):
    __abstract__ = True  # Prevents this class from being mapped to a database table

    id = Column(
        Integer, primary_key=True, index=True
    )  # Unique identifier for each record
    created_at = Column(
        DateTime, default=utc_now
    )  # Timestamp for when the record was created
    updated_at = Column(
        DateTime, default=utc_now, onupdate=utc_now
    )  # Auto-updates on changes
