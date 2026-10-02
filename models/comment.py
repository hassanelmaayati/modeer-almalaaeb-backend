from sqlalchemy import Column, Integer, String, ForeignKey

from sqlalchemy.orm import relationship
from .base import BaseModel
from .user import UserModel

#  CommentModel extends SQLAlchemy's Base class.
#  Extending Base lets SQLAlchemy 'know' about our model, so it can use it.


class CommentModel(BaseModel):

    # This will be used directly to make a
    # TABLE in Postgresql
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)

    # Specific columns for our Comments Table.
    content = Column(String, nullable=False)
    tea_id = Column(Integer, ForeignKey("teas.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tea = relationship("TeaModel", back_populates="comments")
    user = relationship("UserModel", back_populates="comments")
