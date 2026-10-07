import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from models.base import utc_now
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


logger = logging.getLogger(__name__)

# Read notices are gone after 30 days and anything else after 90, so the table cannot grow forever
READ_RETENTION = timedelta(days=30)
ANY_RETENTION = timedelta(days=90)
RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
RETENTION_BATCH = 1000


def purge_old_notifications(db: Session, now=None, batch: int = RETENTION_BATCH) -> int:
    """Delete expired notifications in small batches; returns how many were removed."""
    now = now or utc_now()
    expired = or_(
        and_(NotificationModel.read_at.is_not(None), NotificationModel.created_at < now - READ_RETENTION),
        NotificationModel.created_at < now - ANY_RETENTION,
    )
    removed = 0
    while True:
        ids = [row.id for row in db.query(NotificationModel.id).filter(expired).limit(batch)]
        if not ids:
            return removed
        db.query(NotificationModel).filter(NotificationModel.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        removed += len(ids)


def purge_in_thread(session_factory) -> int:
    db = session_factory()
    try:
        return purge_old_notifications(db)
    finally:
        db.close()


async def retention_loop(interval: float = RETENTION_INTERVAL_SECONDS, first_delay: float = 300,
                         session_factory=None) -> None:
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    # Not at once on boot: a restart should first serve traffic
    await asyncio.sleep(first_delay)
    while True:
        try:
            removed = await asyncio.to_thread(purge_in_thread, session_factory)
            if removed:
                logger.info("Removed %s expired notifications", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Notification retention pass failed")
        await asyncio.sleep(interval)
