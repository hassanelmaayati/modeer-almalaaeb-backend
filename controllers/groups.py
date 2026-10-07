from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response

# DB
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from database import get_db

# Models
from models.group import GroupModel
from models.membership import MembershipModel
from models.user import UserModel
from models.sport import SportModel

# Serializers
from serializers.group import GroupMineSchema, GroupSchema, CreateGroupSchema, UpdateGroupSchema
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


def member_counts(db: Session, group_ids) -> dict[int, int]:
    """People per group in one query: accepted members plus the owner (who has no row)."""
    group_ids = list(group_ids)
    if not group_ids:
        return {}
    rows = dict(
        db.query(MembershipModel.group_id, func.count(MembershipModel.id))
        .filter(
            MembershipModel.group_id.in_(group_ids),
            MembershipModel.cup_id.is_(None),
            MembershipModel.status == "accepted",
        )
        .group_by(MembershipModel.group_id)
        .all()
    )
    return {group_id: rows.get(group_id, 0) + 1 for group_id in group_ids}


def group_views(db: Session, groups, schema=GroupSchema, extra=None):
    """Group responses with member_count (and any per-group extras) from one count query."""
    counts = member_counts(db, [group.id for group in groups])
    views = []
    for group in groups:
        data = GroupSchema.model_validate(group).model_dump()
        data.update(member_count=counts[group.id], **(extra(group) if extra else {}))
        views.append(schema(**data))
    return views


@router.get("/groups", response_model=List[GroupSchema])
def get_groups(
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
):
    query = db.query(GroupModel)
    response.headers["X-Total-Count"] = str(query.count())
    groups = query.order_by(GroupModel.id).offset(offset).limit(limit).all()
    return group_views(db, groups)


# Declared before /groups/{group_id} so "mine" is not read as an id
@router.get("/groups/mine", response_model=List[GroupMineSchema])
def get_my_groups(
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1_000_000),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    joined = db.query(MembershipModel.group_id).filter(
        MembershipModel.user_id == current_user.id,
        MembershipModel.status == "accepted",
        MembershipModel.group_id.is_not(None),
        MembershipModel.cup_id.is_(None),
    )
    query = db.query(GroupModel).filter(or_(GroupModel.owner_id == current_user.id, GroupModel.id.in_(joined)))
    response.headers["X-Total-Count"] = str(query.count())
    groups = query.order_by(GroupModel.id).offset(offset).limit(limit).all()
    return group_views(db, groups, schema=GroupMineSchema,
                       extra=lambda group: {"role": "owner" if group.owner_id == current_user.id else "member"})


@router.get("/groups/{group_id}", response_model=GroupSchema)
def get_group(group_id: int, db: Session = Depends(get_db)):
    group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group_views(db, [group])[0]


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
    return group_views(db, [new_group])[0]


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
    return group_views(db, [db_group])[0]
