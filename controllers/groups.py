from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

# DB
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.group import GroupModel
from models.user import UserModel
from models.sport import SportModel

# Serializers
from serializers.group import GroupSchema, CreateGroupSchema, UpdateGroupSchema
from typing import List

from dependencies.get_current_user import get_current_user
from services.changes import change_events
from services.memberships import commit, load
from services.realtime import queue_events

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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    load(db, SportModel, group.sports_id)
    new_group = GroupModel(**group.model_dump(), owner_id=current_user.id)
    db.add(new_group)
    db.flush()
    events = change_events(db, {"type": "group", "id": new_group.id}, "group.created",
                          "A group was created", current_user.id, notify=False)
    commit(db)
    db.refresh(new_group)
    queue_events(background_tasks, events)
    return new_group


@router.put("/groups/{group_id}", response_model=GroupSchema)
def update_group(
    group_id: int,
    group: UpdateGroupSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_group = load(db, GroupModel, group_id, lock=True)

    if db_group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to update this group"
        )

    for key, value in group.model_dump(exclude_unset=True).items():
        setattr(db_group, key, value)
    events = change_events(db, {"type": "group", "id": group_id}, "group.updated",
                          "A group you joined was updated", current_user.id)
    commit(db)
    db.refresh(db_group)
    queue_events(background_tasks, events)
    return db_group
