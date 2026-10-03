from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from models.user import UserModel
from database import get_db
import jwt
from jwt import (
    ExpiredSignatureError,
    InvalidTokenError,
)
from config.environment import JWT_SECRET

http_bearer = HTTPBearer()


def get_current_user(db: Session = Depends(get_db), token: str = Depends(http_bearer)):

    try:
        payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=["HS256"])

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
        )

    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not decode token: {str(e)}",
        )

    user = db.query(UserModel).filter(UserModel.id == int(payload.get("sub"))).first()

    # A signed-out token carries an older version than the user's current one
    if not user or payload.get("ver") != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is no longer valid, please sign in again",
        )

    return user
