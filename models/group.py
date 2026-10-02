from sqlalchemy import Column, Integer, String, ForeignKey

from sqlalchemy.orm import relationship
from .base import BaseModel
from .user import UserModel
from .sport import SportModel


class GroupModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)

    # columns of the Groups Table.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    photo_url = Column(String, nullable=True)
    sports_id = Column(Integer, ForeignKey("sports.id"), nullable=False)

    # Relationships to other models:
    members = relationship("UserModel", back_populates="group")
    owner = relationship("UserModel", back_populates="owned_groups")
    sport = relationship("SportModel", back_populates="groups")
