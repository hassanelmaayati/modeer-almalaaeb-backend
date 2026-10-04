from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from models.cup import CupModel
from models.membership import MembershipModel
from services.notifications import notify_users
from services.chat_access import group_user_ids, room_user_ids
from services.realtime import user_event


def change_events(db, target, kind, text, actor_id, *, extra_ids=(), notify=True, recipient_ids=None):
    """Prepare private invalidations and saved notices inside the caller's transaction."""
    resource, row_id = target["type"], target["id"]
    if recipient_ids is not None:
        ids = set(recipient_ids)
    elif resource == "room":
        ids = set(room_user_ids(db, row_id))
        ids.update(m.user_id for m in db.query(MembershipModel).filter(
            MembershipModel.room_id == row_id, MembershipModel.status == "pending"))
    elif resource == "group":
        ids = set(group_user_ids(db, row_id))
    elif resource == "cup":
        cup = db.get(CupModel, row_id)
        ids = {cup.organizer_user_id} if cup else set()
        if cup:
            ids.update(e["owner_user_id"] for e in cup.entries)
        ids.update(m.user_id for m in db.query(MembershipModel).filter(
            MembershipModel.cup_id == row_id, MembershipModel.status.in_(("pending", "accepted"))))
    else:
        ids = {row_id}
    ids = set(ids) | set(extra_ids) | {actor_id}
    event_type = "friend.updated" if resource == "direct" else f"{resource}.updated"
    events = [user_event(ids, {"type": event_type, f"{resource}_id": row_id})]
    try:
        if notify:
            notice_target = {"type": "direct", "id": actor_id} if resource == "direct" else target
            events += notify_users(db, ids, kind, notice_target, text, exclude_user_id=actor_id)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This change conflicts with existing data") from error
    return events
