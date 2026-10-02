# models/base.py
from sqlalchemy import Column, DateTime, Integer, func
from sqlalchemy.ext.declarative import declarative_base

# Create a base class for all models
Base = declarative_base()


class BaseModel(Base):
    __abstract__ = True  # Prevents this class from being mapped to a database table

    id = Column(
        Integer, primary_key=True, index=True
    )  # Unique identifier for each record
    created_at = Column(
        DateTime, default=func.now()
    )  # Timestamp for when the record was created
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now()
    )  # Auto-updates on changes
