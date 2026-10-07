from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

import models.user
from models.user import UserModel
from serializers.user import UserSignupSchema, UserLoginSchema, UserTokenSchema
from database import get_db
from dependencies.get_current_user import get_current_user
from services import realtime
from services.accounts import commit_account
from services.rate_limit import (
    LOGIN_BY_EMAIL, LOGIN_BY_IP, SIGNUP_BY_EMAIL, SIGNUP_BY_IP, client_ip,
)

router = APIRouter(tags=["Auth"])

MAX_PASSWORD_LENGTH = 128


@lru_cache
def dummy_hash() -> str:
    return models.user.pwd_context.hash("not-a-real-password")


def credentials_match(db_user: UserModel | None, password: str) -> bool:
    # Always hash once, so an unknown email, a wrong password and an over-long
    # password all cost the same and look the same (401), never revealing which
    # emails are registered
    if db_user is None or len(password) > MAX_PASSWORD_LENGTH:
        try:
            models.user.pwd_context.verify(password[:MAX_PASSWORD_LENGTH], dummy_hash())
        except ValueError:
            pass
        return False
    return db_user.verify_password(password)


@router.post("/auth/signup", response_model=UserTokenSchema, status_code=201)
def signup(user: UserSignupSchema, request: Request, db: Session = Depends(get_db)):
    # Every attempt counts, so bulk account creation is slowed down
    SIGNUP_BY_IP.hit(client_ip(request))
    SIGNUP_BY_EMAIL.hit(user.email)

    if db.query(UserModel).filter(func.lower(UserModel.user_name) == user.user_name.lower()).first():
        raise HTTPException(status_code=400, detail="user name is already taken")

    if db.query(UserModel).filter(UserModel.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email is already registered")

    new_user = UserModel(
        user_name=user.user_name,
        email=user.email,
        photo_url=user.photo_url or None,
        bio=user.bio or None,
        district=user.district,
    )
    new_user.set_password(user.password)
    db.add(new_user)
    commit_account(db)
    db.refresh(new_user)
    token = new_user.generate_jwt()
    return {"token": token, "msg": "User registered successfully", "user": new_user}


@router.post("/auth/login", response_model=UserTokenSchema)
def login(user: UserLoginSchema, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    LOGIN_BY_IP.check(ip)
    LOGIN_BY_EMAIL.check(user.email)

    db_user = db.query(UserModel).filter(UserModel.email == user.email).first()

    # Check if the user exists and if the password is correct
    if not credentials_match(db_user, user.password):
        # Only failures count, and a success clears the email's count
        LOGIN_BY_IP.record(ip)
        LOGIN_BY_EMAIL.record(user.email)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    LOGIN_BY_EMAIL.reset(user.email)

    token = db_user.generate_jwt()
    return {"token": token, "msg": "Login successful", "user": db_user}


@router.post("/auth/logout", status_code=204)
def logout(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Revokes every token issued so far, on all devices
    old_version = current_user.token_version
    current_user.token_version += 1
    db.commit()
    background_tasks.add_task(realtime.realtime_hub.close_user, current_user.id, old_version)
    return None
