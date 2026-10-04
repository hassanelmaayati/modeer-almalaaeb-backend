from sqlalchemy.orm import Session
from models.notification import NotificationModel
from serializers.notification import NotificationSchema, NotificationTargetSchema
from services.realtime import user_event


def notify_users(db: Session, user_ids, kind: str, target: dict, text: str, exclude_user_id: int | None = None) -> list[dict]:
    """Add durable notices to the caller's transaction; queue returned events after commit."""
    target = NotificationTargetSchema.model_validate(target).model_dump()
    kind, text = kind.strip(), text.strip()
    if not kind or not text:
        raise ValueError("Notification kind and text are required")
    rows = [NotificationModel(user_id=user_id, kind=kind, target=target, text=text) for user_id in sorted(set(user_ids)) if user_id != exclude_user_id]
    db.add_all(rows)
    db.flush()
    return [user_event([row.user_id], {"type": "notification.created", "notification": NotificationSchema.model_validate(row).model_dump(mode="json")}) for row in rows]
