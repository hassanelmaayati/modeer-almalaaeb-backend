from sqlalchemy import Column, Integer, String, ForeignKey, Boolean

from sqlalchemy.orm import relationship
from .base import BaseModel
from .user import UserModel

from .room import RoomModel
from .cup import CupModel
from .group import GroupModel


class MembershipModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)

    # columns of the Memberships Table.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    other_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=True)
    cup_id = Column(Integer, ForeignKey("cups.id"), nullable=True)

    status = Column(String, nullable=False)
    position = Column(String, nullable=True)
    attendance = Column(String, nullable=True)
    rating = Column(Integer, nullable=True)

    requested = Column(Boolean, nullable=True)
    accepted = Column(Boolean, nullable=True)

    user_blocked_other = Column(String, nullable=True)
    other_blocked_user = Column(String, nullable=True)

    # Relationships to other models:
    user = relationship(
        "UserModel", back_populates="memberships", foreign_keys=[user_id]
    )
    room = relationship("RoomModel", back_populates="memberships")
    cup = relationship("CupModel", back_populates="memberships")
    group = relationship("GroupModel", back_populates="memberships")
