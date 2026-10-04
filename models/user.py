from sqlalchemy import Column, Integer, String, Text
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

    # Public profile
    user_name = Column(String, nullable=False, unique=True)
    photo_url = Column(String, nullable=True, default="")
    bio = Column(Text, nullable=True, default="")

    # Private login fields; google_subject links an optional Google sign-in
    email = Column(String, nullable=False, unique=True)
    password = Column(String, nullable=False)
    google_subject = Column(String, nullable=True, unique=True)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    # Relationships with other models
    memberships = relationship(
        "MembershipModel",
        back_populates="user",
        foreign_keys="MembershipModel.user_id",
    )
    owned_groups = relationship("GroupModel", back_populates="owner")
<<<<<<< HEAD
    organized_cups = relationship("CupModel", back_populates="organizer")
=======
    hosted_rooms = relationship(
        "RoomModel", back_populates="host", foreign_keys="RoomModel.host_id"
    )
    sent_messages = relationship(
        "MessageModel", back_populates="sender", foreign_keys="MessageModel.sender_id"
    )
    received_messages = relationship(
        "MessageModel",
        back_populates="recipient",
        foreign_keys="MessageModel.recipient_id",
    )
>>>>>>> 38ca36c9404cf6d093c5db0b75c6a780b4a04ee5

    def set_password(self, password: str):
        self.password = pwd_context.hash(password)

    def verify_password(self, password: str) -> bool:
        if not self.password:
            return False
        return pwd_context.verify(password, self.password)

    def generate_jwt(self):
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(days=1),
            "iat": datetime.now(timezone.utc),
            "sub": str(self.id),
            "ver": self.token_version,
        }

        token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
        return token
