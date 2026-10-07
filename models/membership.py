from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, case
from sqlalchemy.sql.expression import Grouping

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
    # When a room request or invitation was accepted (UTC); orders who joined first
    accepted_at = Column(DateTime, nullable=True)

    user_blocked_other = Column(String, nullable=True)
    other_blocked_user = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "room_id", name="uq_memberships_user_room"),
        UniqueConstraint("user_id", "cup_id", name="uq_memberships_user_cup"),
        Index("uq_memberships_user_group", user_id, group_id, unique=True,
              postgresql_where=(group_id.is_not(None) & cup_id.is_(None)),
              sqlite_where=(group_id.is_not(None) & cup_id.is_(None))),
        Index("uq_memberships_friend_pair",
              Grouping(case((user_id < other_user_id, user_id), else_=other_user_id)),
              Grouping(case((user_id < other_user_id, other_user_id), else_=user_id)), unique=True,
              postgresql_where=other_user_id.is_not(None), sqlite_where=other_user_id.is_not(None)),
        Index("uq_memberships_room_position", room_id, position, unique=True,
              postgresql_where=(status == "accepted") & position.is_not(None),
              sqlite_where=(status == "accepted") & position.is_not(None)),
        # The user-first indexes above cannot serve "who is in this room/group/cup"
        Index("ix_memberships_room_id_status", room_id, status),
        Index("ix_memberships_group_id_status", group_id, status),
        Index("ix_memberships_cup_id_status", cup_id, status),
        # Friend lookups from the other side of the pair
        Index("ix_memberships_other_user_id", other_user_id, postgresql_where=other_user_id.is_not(None)),
    )

    # Relationships to other models:
    user = relationship(
        "UserModel", back_populates="memberships", foreign_keys=[user_id]
    )
    room = relationship("RoomModel", back_populates="memberships")
    cup = relationship("CupModel", back_populates="memberships")
    group = relationship("GroupModel", back_populates="memberships")
