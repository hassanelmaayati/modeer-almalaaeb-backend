from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
import jwt

from config.environment import JWT_SECRET
from database import get_db
from models.user import UserModel

http_bearer = HTTPBearer()


def decode_access_token(token: str) -> dict:
    """Validate the same JWT for HTTP requests, socket tickets and active sockets."""
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], options={"require": ["exp", "sub", "ver"]})
        if not str(claims["sub"]).isdigit() or int(claims["sub"]) < 1:
            raise jwt.InvalidTokenError("Invalid subject")
        if type(claims["ver"]) is not int:
            raise jwt.InvalidTokenError("Invalid token version")
        return claims
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except (jwt.InvalidTokenError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Could not decode token")


def user_from_token(db: Session, token: str) -> UserModel:
    claims = decode_access_token(token)
    user = db.query(UserModel).filter(UserModel.id == int(claims["sub"])).populate_existing().first()
    if not user or claims["ver"] != user.token_version:
        raise HTTPException(status_code=401, detail="Token is no longer valid, please sign in again")
    return user


def get_current_user(db: Session = Depends(get_db), token=Depends(http_bearer)):
    return user_from_token(db, token.credentials)
