from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, UniqueConstraint

from .base import BaseModel


class PlayerRatingModel(BaseModel):
    """One player's star rating of another player for one completed room."""

    __tablename__ = "player_ratings"

    rater_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ratee_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    stars = Column(Integer, nullable=False)

    __table_args__ = (
        # Ratings are final: one per rater, per ratee, per room, never updated
        UniqueConstraint(
            "rater_id", "ratee_id", "room_id", name="uq_player_ratings_rater_ratee_room"
        ),
        CheckConstraint("stars BETWEEN 1 AND 5", name="ck_player_ratings_stars"),
        CheckConstraint("rater_id <> ratee_id", name="ck_player_ratings_not_self"),
        # The profile average reads every rating a user received
        Index("ix_player_ratings_ratee_id", "ratee_id"),
    )
