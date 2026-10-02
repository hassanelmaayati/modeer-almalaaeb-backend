from fastapi import APIRouter, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.tea import TeaModel
from models.comment import CommentModel
from models.user import UserModel

# Serializers
from serializers.comment import CommentSchema, CreateCommentSchema, UpdateCommentSchema
from typing import List

from dependencies.get_current_user import get_current_user

router = APIRouter(
    tags=[
        "Comments Management",
    ]
)


@router.get("/teas/{tea_id}/comments", response_model=List[CommentSchema])
def get_comments(tea_id: int, db: Session = Depends(get_db)):
    tea = db.query(TeaModel).filter(TeaModel.id == tea_id).first()
    if not tea:
        raise HTTPException(status_code=404, detail="Tea not found")
    return tea.comments


@router.get("/comments/{comment_id}", response_model=CommentSchema)
def get_comments(comment_id: int, db: Session = Depends(get_db)):
    comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.post("/teas/{tea_id}/comments", response_model=CommentSchema, status_code=201)
def create_comments(
    tea_id: int,
    comment: CreateCommentSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    tea = db.query(TeaModel).filter(TeaModel.id == tea_id).first()
    if not tea:
        raise HTTPException(status_code=404, detail="Tea not found")
    new_comment = CommentModel(**comment.dict(), tea_id=tea_id, user_id=current_user.id)
    db.add(new_comment)
    db.commit()
    db.refresh(new_comment)
    return new_comment


@router.put("/comments/{comment_id}", response_model=CommentSchema)
def update_comment(
    comment_id: int,
    comment: UpdateCommentSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if not db_comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if db_comment.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to update this comment"
        )

    for key, value in comment.dict(exclude_unset=True).items():
        setattr(db_comment, key, value)
    db.commit()
    db.refresh(db_comment)
    return db_comment


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_comment = db.query(CommentModel).filter(CommentModel.id == comment_id).first()
    if not db_comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if db_comment.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this comment"
        )

    db.delete(db_comment)
    db.commit()
    return None
