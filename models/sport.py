from sqlalchemy import Column, Integer, String, ForeignKey

from sqlalchemy.orm import relationship
from .base import BaseModel


class SportModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "sports"

    id = Column(Integer, primary_key=True, index=True)

    # columns of the Sports Table.
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)

    # Relationships to other models:
    groups = relationship("GroupModel", back_populates="sport")
