from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.base import utc_now
from dependencies.get_current_user import get_current_user
from dependencies.get_optional_user import get_optional_user
from models.membership import MembershipModel
from models.user import UserModel
from serializers.membership import CreateRoomMemberSchema, RoomMemberSchema, UpdateRoomMemberSchema
from services.changes import change_events
from services.lobby_events import lobby_state, queue_room_events
from services.memberships import commit, load
from services.realtime import queue_events
from services.room_access import load_visible_room, valid_positions
from services.room_rules import count_slots_left, is_past_cutoff, as_utc
from datetime import datetime, timezone

router = APIRouter(tags=["Room Members Management"])


def members(db, room_id):
    return db.query(MembershipModel).filter(MembershipModel.room_id == room_id)


def require_admission(room):
    if room.status != "open" or is_past_cutoff(room):
        raise HTTPException(409, "Admission is closed")


def without_rating(member):
    # Host ratings are private to the host; everyone else, even the rated player, sees null
    return RoomMemberSchema.model_validate(member).model_copy(update={"rating": None})


def finish(db, background_tasks, room, before, actor_id, member, text):
    room.revision += 1
    events = change_events(db, {"type": "room", "id": room.id}, "room.membership",
                          text, actor_id, extra_ids=[member.user_id])
    commit(db)
    db.refresh(member)
    queue_room_events(background_tasks, db, room, before)
    queue_events(background_tasks, events)
    return member if actor_id == room.host_id else without_rating(member)


@router.get("/rooms/{room_id}/members", response_model=list[RoomMemberSchema])
def get_room_members(room_id: int, db: Session = Depends(get_db),
                     current_user: UserModel | None = Depends(get_optional_user)):
    room = load_visible_room(db, room_id, current_user)
    query = members(db, room_id)
    own = query.filter(MembershipModel.user_id == current_user.id).first() if current_user else None
    is_host = current_user is not None and current_user.id == room.host_id
    admitted = own is not None and own.status == "accepted"
    if is_host:
        return query.all()
    visible = query.filter(MembershipModel.status == "accepted").all() if admitted else [own] if own else []
    return [without_rating(row) for row in visible]


@router.post("/rooms/{room_id}/members", response_model=RoomMemberSchema, status_code=201)
def create_room_member(room_id: int, membership: CreateRoomMemberSchema,
                       background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                       current_user: UserModel = Depends(get_current_user)):
    # Hidden rooms are 404 before anything else, so a closed private room never answers 409
    room = load_visible_room(db, room_id, current_user, lock=True)
    require_admission(room)
    target_id = membership.user_id if membership.user_id is not None else current_user.id
    is_self = target_id == current_user.id
    if not is_self and current_user.id != room.host_id:
        raise HTTPException(403, "Only the host can invite")
    if target_id == room.host_id:
        raise HTTPException(409, "The host already has a place")
    load(db, UserModel, target_id)
    if members(db, room_id).filter(MembershipModel.user_id == target_id).first():
        raise HTTPException(409, "Already requested or a member")
    if count_slots_left(db, room) == 0:
        raise HTTPException(409, "The room is full")
    # An open room accepts a player's own request at once (the free place was checked
    # above, under the room lock); invitations always wait for the invitee
    instant = is_self and room.admission_policy == "open"
    before = lobby_state(db, room) if instant else None
    member = MembershipModel(user_id=target_id, room_id=room_id, status="accepted" if instant else "pending",
                             requested=is_self, accepted=instant, accepted_at=utc_now() if instant else None)
    db.add(member)
    if instant:
        db.flush()
        return finish(db, background_tasks, room, before, current_user.id, member, "A player joined a room")
    events = change_events(db, {"type": "room", "id": room_id},
                          "room.request" if is_self else "room.invitation",
                          "A player requested a place" if is_self else "You were invited to a room",
                          current_user.id, recipient_ids={room.host_id, target_id})
    commit(db)
    db.refresh(member)
    queue_events(background_tasks, events)
    return member


@router.patch("/rooms/{room_id}/members/{user_id}", response_model=RoomMemberSchema)
def update_room_member(room_id: int, user_id: int, membership: UpdateRoomMemberSchema,
                       background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                       current_user: UserModel = Depends(get_current_user)):
    room = load_visible_room(db, room_id, current_user, lock=True)
    member = members(db, room_id).filter(MembershipModel.user_id == user_id).first()
    if not member:
        raise HTTPException(404, "Room member not found")
    is_host, is_self = current_user.id == room.host_id, current_user.id == user_id
    if not (is_host or is_self):
        raise HTTPException(403, "Not allowed")
    before = lobby_state(db, room)
    data = membership.model_dump(exclude_unset=True)
    status = data.get("status")
    if status is not None:
        allowed = set()
        if member.status == "pending" and ((is_host and member.requested) or (is_self and not member.requested)):
            allowed.update(("accepted", "declined"))
        if is_host and not is_self and member.status in ("pending", "accepted"):
            allowed.add("removed")
        if is_self and member.status in ("pending", "accepted"):
            allowed.add("left")
        if status not in allowed:
            raise HTTPException(403, f"Cannot change status from {member.status} to {status}")
        if status == "accepted":
            require_admission(room)
            if count_slots_left(db, room) == 0:
                raise HTTPException(409, "The room is full")
        member.status, member.accepted = status, status == "accepted"
        if status == "accepted":
            member.accepted_at = utc_now()
        if status != "accepted":
            member.position = None
    if "position" in data:
        if member.status != "accepted":
            raise HTTPException(409, "Only accepted players have a slot")
        if room.status != "open" or datetime.now(timezone.utc) >= as_utc(room.starts_at):
            raise HTTPException(409, "Slot selection is closed")
        position = data["position"].strip() if data["position"] is not None else None
        if position is not None:
            # Only the room's own slots can be claimed (numbered places when it has no layout)
            if position not in valid_positions(room):
                raise HTTPException(422, "Unknown position, choose one of the room's slots")
            if members(db, room_id).filter(MembershipModel.status == "accepted",
                    MembershipModel.position == position, MembershipModel.id != member.id).first():
                raise HTTPException(409, "Slot already taken")
        member.position = position
    if data.get("attendance") is not None:
        if not is_host:
            raise HTTPException(403, "Only the host records attendance")
        member.attendance = data["attendance"]
    if data.get("rating") is not None:
        if not is_host or is_self:
            raise HTTPException(403, "Only the host can rate other players")
        # The host's rating is one final rating per player, after the room is over
        if room.status != "completed":
            raise HTTPException(409, "Ratings open when the room is completed")
        if member.status != "accepted":
            raise HTTPException(409, "Only accepted players can be rated")
        if member.attendance != "present":
            raise HTTPException(409, "Rate only present players")
        if member.rating is not None:
            raise HTTPException(409, "This player is already rated")
        member.rating = data["rating"]
    return finish(db, background_tasks, room, before, current_user.id, member,
                  "A room membership was updated")


@router.delete("/rooms/{room_id}/members/me", status_code=204)
def leave_room(room_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
               current_user: UserModel = Depends(get_current_user)):
    room = load_visible_room(db, room_id, current_user, lock=True)
    if room.host_id == current_user.id:
        raise HTTPException(409, "The host cannot leave their room")
    member = members(db, room_id).filter(MembershipModel.user_id == current_user.id).first()
    if not member:
        raise HTTPException(404, "Room member not found")
    if member.status == "left":
        return None
    if member.status not in ("pending", "accepted"):
        raise HTTPException(409, "Membership is already closed")
    before = lobby_state(db, room)
    member.status, member.accepted, member.position = "left", False, None
    finish(db, background_tasks, room, before, current_user.id, member, "A player left a room")
