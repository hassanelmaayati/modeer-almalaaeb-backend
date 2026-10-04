from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from database import get_db
from dependencies.get_current_user import get_current_user
from models.notification import NotificationModel
from models.user import UserModel
from serializers.notification import NotificationListSchema, NotificationSchema, ReadNotificationsSchema
from services.realtime import queue_events, user_event

router = APIRouter(tags=["Notifications"])


def own_notifications(db: Session, user_id: int):
    return db.query(NotificationModel).filter(NotificationModel.user_id == user_id)


@router.get("/notifications", response_model=NotificationListSchema)
def get_notifications(before: int | None = Query(None, gt=0), limit: int = Query(50, ge=1, le=100), unread_only: bool = False,
                      db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    own = own_notifications(db, current_user.id)
    unread_count = own.filter(NotificationModel.read_at.is_(None)).count()
    query = own.filter(NotificationModel.read_at.is_(None)) if unread_only else own
    if before is not None:
        query = query.filter(NotificationModel.id < before)
    return {"items": query.order_by(NotificationModel.id.desc()).limit(limit).all(), "unread_count": unread_count}


@router.patch("/notifications", status_code=204)
def read_all(body: ReadNotificationsSchema, background_tasks: BackgroundTasks,
             db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    own_notifications(db, current_user.id).filter(NotificationModel.read_at.is_(None)).update({NotificationModel.read_at: datetime.now(timezone.utc).replace(tzinfo=None)}, synchronize_session=False)
    db.commit()
    queue_events(background_tasks, [user_event([current_user.id], {"type": "notifications.updated"})])


@router.patch("/notifications/{notification_id}", response_model=NotificationSchema)
def read_one(notification_id: int, body: ReadNotificationsSchema, background_tasks: BackgroundTasks,
             db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    notice = own_notifications(db, current_user.id).filter(NotificationModel.id == notification_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notice.read_at is None:
        notice.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(notice)
    queue_events(background_tasks, [user_event([current_user.id], {"type": "notifications.updated"})])
    return notice
