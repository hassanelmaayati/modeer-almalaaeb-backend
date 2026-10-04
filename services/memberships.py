from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


def load(db, model, row_id, *, lock=False):
    query = db.query(model).filter(model.id == row_id)
    row = (query.with_for_update().populate_existing() if lock else query).first()
    if row is None:
        raise HTTPException(404, f"{model.__tablename__.rstrip('s').title()} not found")
    return row


def commit(db):
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(409, "This change conflicts with existing data") from error


def invitation_transition(row, new_status, *, is_self, is_owner):
    allowed = set()
    if is_self and row.status == "pending":
        allowed.update(("accepted", "declined", "left"))
    if is_self and row.status == "accepted":
        allowed.add("left")
    if is_owner and not is_self and row.status in ("pending", "accepted"):
        allowed.add("removed")
    if new_status not in allowed:
        raise HTTPException(403, f"Cannot change status from {row.status} to {new_status}")
    row.status, row.accepted = new_status, new_status == "accepted"
