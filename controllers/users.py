from fastapi import APIRouter, HTTPException, Depends, Query
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
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    # Ordered by id so pages stay stable as users sign up
    return db.query(UserModel).order_by(UserModel.id).offset(offset).limit(limit).all()


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
    if new_user_name and new_user_name != db_user.user_name:
        taken = db.query(UserModel).filter(UserModel.user_name == new_user_name)
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
