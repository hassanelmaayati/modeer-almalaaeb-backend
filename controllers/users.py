from fastapi import APIRouter, HTTPException, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import List

from models.user import UserModel
from serializers.user import (
    UserSchema,
    UserPrivateSchema,
    UserUpdateSchema,
)
from database import get_db
from dependencies.get_current_user import get_current_user
from services.accounts import commit_account

router = APIRouter(tags=["Users Management"])


@router.get("/users", response_model=List[UserSchema])
def get_users(
    response: Response,
    ids: str | None = Query(None, max_length=1000, description="Comma-separated ids, at most 100; paging is ignored"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
):
    if ids is not None:
        # Batch lookup of public profiles; ids that do not exist are simply left out
        try:
            wanted = sorted({int(part) for part in ids.split(",")})
        except ValueError:
            raise HTTPException(status_code=422, detail="ids must be comma-separated integers")
        if len(wanted) > 100 or any(not 0 < user_id <= 2_147_483_647 for user_id in wanted):
            raise HTTPException(status_code=422, detail="send between 1 and 100 valid ids")
        users = db.query(UserModel).filter(UserModel.id.in_(wanted)).order_by(UserModel.id).all()
        response.headers["X-Total-Count"] = str(len(users))
        return users
    query = db.query(UserModel)
    response.headers["X-Total-Count"] = str(query.count())
    # Ordered by id so pages stay stable as users sign up
    return query.order_by(UserModel.id).offset(offset).limit(limit).all()


@router.get("/users/me", response_model=UserPrivateSchema)
def get_me(current_user: UserModel = Depends(get_current_user)):
    return current_user


@router.put("/users/me", response_model=UserPrivateSchema)
def update_me(
    user: UserUpdateSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_user = db.query(UserModel).filter(UserModel.id == current_user.id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user.model_dump(exclude_unset=True)

    new_user_name = user_data.get("user_name")
    # Names are unique ignoring case; changing only the case of your own name is fine
    if new_user_name and new_user_name.lower() != db_user.user_name.lower():
        taken = db.query(UserModel.id).filter(func.lower(UserModel.user_name) == new_user_name.lower())
        if taken.first():
            raise HTTPException(status_code=400, detail="user name is already taken")

    for key, value in user_data.items():
        if key in ("user_name",) and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
        setattr(db_user, key, value)

    commit_account(db)
    db.refresh(db_user)
    return db_user


@router.get("/users/{user_id}", response_model=UserSchema)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
