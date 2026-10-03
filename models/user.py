from sqlalchemy import CheckConstraint, Column, Integer, String, Text
from .base import BaseModel
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import jwt
from config.environment import JWT_SECRET
from sqlalchemy.orm import relationship

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserModel(BaseModel):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "password_hash IS NOT NULL OR google_subject IS NOT NULL",
            name="ck_users_login_method",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Public profile
    display_name = Column(String, nullable=False)
    handle = Column(String, nullable=False, unique=True)
    avatar_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)

    # Private login fields; a user needs a password, a Google identity, or both
    email = Column(String, nullable=True, unique=True)
    password_hash = Column(String, nullable=True)
    google_subject = Column(String, nullable=True, unique=True)

    # Bumping this revokes every token signed with an older version
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    # Relationships with other models
    group = relationship("GroupModel", back_populates="members")
    owned_groups = relationship("GroupModel", back_populates="owner")

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def google_linked(self) -> bool:
        return self.google_subject is not None

    def set_password(self, password: str):
        self.password_hash = pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return pwd_context.verify(password, self.password_hash)

    def generate_jwt(self):
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "iat": datetime.now(timezone.utc),
            "sub": str(self.id),
            "ver": self.token_version,
        }

        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return token
