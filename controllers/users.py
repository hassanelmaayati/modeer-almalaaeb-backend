from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List

from models.user import UserModel
from serializers.user import (
    UserSchema,
    UserUpdateSchema,
)
from database import get_db
from dependencies.get_current_user import get_current_user

router = APIRouter(tags=["Users Management"])


@router.get("/users", response_model=List[UserSchema])
def get_users(
    db: Session = Depends(get_db),
):
    return db.query(UserModel).all()


@router.get("/users/me", response_model=UserSchema)
def get_me(current_user: UserModel = Depends(get_current_user)):
    return current_user


@router.put("/users/me", response_model=UserSchema)
def update_me(
    user: UserUpdateSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_user = db.query(UserModel).filter(UserModel.id == current_user.id).first()

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    user_data = user.model_dump(exclude_unset=True)
    for key, value in user_data.items():
        if key in ("user_name",) and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
        setattr(db_user, key, value)

    db.commit()
    db.refresh(db_user)
    return db_user


@router.get("/users/{user_id}", response_model=UserSchema)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
