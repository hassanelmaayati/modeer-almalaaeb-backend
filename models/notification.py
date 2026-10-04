from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from .base import BaseModel


class NotificationModel(BaseModel):
    __tablename__ = "notifications"

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String, nullable=False)
    target = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    text = Column(Text, nullable=False)
    read_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("length(trim(kind)) > 0", name="ck_notifications_kind_not_blank"),
        CheckConstraint("length(trim(text)) > 0", name="ck_notifications_text_not_blank"),
        Index("ix_notifications_user_id_id", "user_id", "id"),
        Index("ix_notifications_user_unread", "user_id", "read_at"),
    )
