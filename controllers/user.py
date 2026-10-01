from os import stat

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from models.user import UserModel
from serializers.user import (
    UserRegistrationSchema,
    UserSchema,
    UserTokenSchema,
    UserLoginSchema,
)
from database import get_db

router = APIRouter(tags=["Users Management"])


@router.post("/register", response_model=UserTokenSchema, status_code=201)
def create_user(user: UserRegistrationSchema, db: Session = Depends(get_db)):

    existing_user = (
        db.query(UserModel)
        .filter((UserModel.username == user.username) | (UserModel.email == user.email))
        .first()
    )

    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    new_user = UserModel(username=user.username, email=user.email)
    new_user.set_password(user.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    token = new_user.generate_jwt()
    return {"token": token, "msg": "User registered successfully"}


@router.post("/login", response_model=UserTokenSchema, status_code=201)
def login(user: UserLoginSchema, db: Session = Depends(get_db)):

    db_user = db.query(UserModel).filter(UserModel.username == user.username).first()

    # Check if the user exists and if the password is correct
    if not db_user or not db_user.verify_password(user.password):
        raise HTTPException(status_code=400, detail="Invalid username or password")

    # Generate JWT token
    token = db_user.generate_jwt()

    # Return token and a success message
    return {"token": token, "msg": "Login successful"}
