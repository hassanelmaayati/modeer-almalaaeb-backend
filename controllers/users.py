from fastapi import APIRouter, HTTPException, Depends
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

router = APIRouter(tags=["Users Management"])


@router.get("/users", response_model=List[UserSchema])
def get_users(
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    query = db.query(UserModel)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            UserModel.handle.ilike(pattern) | UserModel.display_name.ilike(pattern)
        )

    return query.order_by(UserModel.display_name).all()


@router.get("/users/me", response_model=UserPrivateSchema)
def get_me(current_user: UserModel = Depends(get_current_user)):
    return current_user


@router.patch("/users/me", response_model=UserPrivateSchema)
def update_me(
    user: UserUpdateSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    user_data = user.model_dump(exclude_unset=True)

    if "handle" in user_data and user_data["handle"] != current_user.handle:
        taken = db.query(UserModel).filter(UserModel.handle == user_data["handle"])
        if taken.first():
            raise HTTPException(status_code=400, detail="Handle is already taken")

    for key, value in user_data.items():
        if key in ("display_name", "handle") and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
        setattr(current_user, key, value)

    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/users/{user_id}", response_model=UserSchema)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

