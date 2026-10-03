from fastapi import APIRouter, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.group import GroupModel
from models.user import UserModel

# Serializers
from serializers.group import GroupSchema, CreateGroupSchema, UpdateGroupSchema
from typing import List

from dependencies.get_current_user import get_current_user

router = APIRouter(
    tags=[
        "Groups Management",
    ]
)


@router.get("/groups", response_model=List[GroupSchema])
def get_groups(db: Session = Depends(get_db)):
    return db.query(GroupModel).all()


@router.get("/groups/{group_id}", response_model=GroupSchema)
def get_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.post("/groups", response_model=GroupSchema, status_code=201)
def create_group(
    group: CreateGroupSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):

    new_group = GroupModel(**group.dict(), owner_id=current_user.id)
    db.add(new_group)
    db.commit()
    db.refresh(new_group)
    return new_group


@router.put("/groups/{group_id}", response_model=GroupSchema)
def update_group(
    group_id: int,
    group: UpdateGroupSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not db_group:
        raise HTTPException(status_code=404, detail="Group not found")

    if db_group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to update this group"
        )

    for key, value in group.dict(exclude_unset=True).items():
        setattr(db_group, key, value)
    db.commit()
    db.refresh(db_group)
    return db_group
