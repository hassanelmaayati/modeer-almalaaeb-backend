from sqlalchemy import Column, Integer, String
from .base import BaseModel
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import jwt
from config.environment import JWT_SECRET
from sqlalchemy.orm import relationship

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserModel(BaseModel):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    teas = relationship("TeaModel", back_populates="user")
    comments = relationship("CommentModel", back_populates="user")
    role = Column(String, nullable=False, default="user")

    def set_password(self, password: str):
        self.password = pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        return pwd_context.verify(password, self.password)

    def generate_jwt(self):
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "iat": datetime.now(timezone.utc),
            "sub": str(self.id),
            "role": self.role,
        }

        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return token
