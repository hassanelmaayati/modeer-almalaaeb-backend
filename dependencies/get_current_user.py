from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from models.user import UserModel
from database import get_db
import jwt
from jwt import (
    DecodeError,
    ExpiredSignatureError,
)
from config.environment import JWT_SECRET

http_bearer = HTTPBearer()


def get_current_user(db: Session = Depends(get_db), token: str = Depends(http_bearer)):

    try:
        payload = jwt.decode(token.credentials, JWT_SECRET, algorithms=["HS256"])

        user = db.query(UserModel).filter(UserModel.id == payload.get("sub")).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password",
            )

    except DecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Could not decode token: {str(e)}",
        )

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Token has expired"
        )

    return user
