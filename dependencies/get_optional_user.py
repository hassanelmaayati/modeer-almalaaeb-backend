from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from database import get_db
from dependencies.get_current_user import get_current_user

optional_bearer = HTTPBearer(auto_error=False)


def get_optional_user(
    db: Session = Depends(get_db), token: str | None = Depends(optional_bearer)
):
    # Guests may browse; a missing or stale token just means "not signed in"
    if not token:
        return None

    try:
        return get_current_user(db, token)
    except HTTPException:
        return None
