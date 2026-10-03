from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from models.user import UserModel
from serializers.user import (
    UserSignupSchema,
    UserLoginSchema,
    UserTokenSchema,
)
from database import get_db
from dependencies.get_current_user import get_current_user

router = APIRouter(tags=["Auth"])


@router.post("/auth/signup", response_model=UserTokenSchema, status_code=201)
def signup(user: UserSignupSchema, db: Session = Depends(get_db)):

    if db.query(UserModel).filter(UserModel.handle == user.handle).first():
        raise HTTPException(status_code=400, detail="Handle is already taken")

    if db.query(UserModel).filter(UserModel.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email is already registered")

    new_user = UserModel(
        display_name=user.display_name, handle=user.handle, email=user.email
    )
    new_user.set_password(user.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    token = new_user.generate_jwt()
    return {"token": token, "msg": "User registered successfully", "user": new_user}


@router.post("/auth/login", response_model=UserTokenSchema)
def login(user: UserLoginSchema, db: Session = Depends(get_db)):

    identifier = user.identifier.strip().lower()
    db_user = (
        db.query(UserModel)
        .filter((UserModel.handle == identifier) | (UserModel.email == identifier))
        .first()
    )

    # Check if the user exists and if the password is correct
    if not db_user or not db_user.verify_password(user.password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = db_user.generate_jwt()
    return {"token": token, "msg": "Login successful", "user": db_user}


@router.post("/auth/logout", status_code=204)
def logout(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    # Revokes every token issued so far, on all devices
    current_user.token_version += 1
    db.commit()
    return None
