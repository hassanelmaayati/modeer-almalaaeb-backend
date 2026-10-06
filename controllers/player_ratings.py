from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from dependencies.get_current_user import get_current_user
from models.membership import MembershipModel
from models.player_rating import PlayerRatingModel
from models.room import RoomModel
from models.user import UserModel
from serializers.player_rating import (
    CreatePlayerRatingSchema,
    PlayerRatingSchema,
    UserRatingSchema,
)
from services.accounts import unique_constraint
from services.memberships import load

router = APIRouter(tags=["Player Ratings"])

ONCE_PER_PAIR = "uq_player_ratings_rater_ratee_room"


def find_room(db: Session, room_id: int, user: UserModel) -> RoomModel:
    room = load(db, RoomModel, room_id)
    if room.visibility != "public":
        # Same rule as the members list: other rooms do not exist for outsiders
        own = db.query(MembershipModel).filter(
            MembershipModel.room_id == room.id, MembershipModel.user_id == user.id
        ).first()
        admitted = user.id == room.host_id or (own is not None and own.status == "accepted")
        invited = own is not None and own.status == "pending" and not own.requested
        if not (admitted or invited):
            raise HTTPException(status_code=404, detail="Room not found")
    return room


def took_part(db: Session, room: RoomModel, user_id: int) -> bool:
    # Participants are the host and the accepted members. A recorded no-show did
    # not take part; attendance is NULL until the host records it, so NULL counts.
    if user_id == room.host_id:
        return True
    return (
        db.query(MembershipModel.id)
        .filter(
            MembershipModel.room_id == room.id,
            MembershipModel.user_id == user_id,
            MembershipModel.status == "accepted",
            or_(MembershipModel.attendance.is_(None), MembershipModel.attendance != "no_show"),
        )
        .first()
        is not None
    )


@router.post("/rooms/{room_id}/ratings", response_model=PlayerRatingSchema, status_code=201)
def rate_player(
    room_id: int,
    rating: CreatePlayerRatingSchema,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    room = find_room(db, room_id, current_user)
    if not took_part(db, room, current_user.id):
        raise HTTPException(status_code=403, detail="Only players who took part in this room can rate")
    if room.status != "completed":
        raise HTTPException(status_code=409, detail="Ratings open when the room is completed")
    # The host already rates players through attendance (memberships.rating)
    if current_user.id == room.host_id:
        raise HTTPException(
            status_code=409, detail="The host rates players through attendance, not here"
        )
    if rating.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot rate yourself")
    load(db, UserModel, rating.user_id)
    if not took_part(db, room, rating.user_id):
        raise HTTPException(status_code=400, detail="That user did not take part in this room")

    already = db.query(PlayerRatingModel.id).filter(
        PlayerRatingModel.rater_id == current_user.id,
        PlayerRatingModel.ratee_id == rating.user_id,
        PlayerRatingModel.room_id == room.id,
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="You already rated this player for this room")

    db.add(
        PlayerRatingModel(
            rater_id=current_user.id,
            ratee_id=rating.user_id,
            room_id=room.id,
            stars=rating.stars,
        )
    )
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        # Two simultaneous requests can both pass the check above; the constraint decides
        if unique_constraint(error) != ONCE_PER_PAIR:
            raise
        raise HTTPException(
            status_code=409, detail="You already rated this player for this room"
        ) from error
    return {"user_id": rating.user_id, "stars": rating.stars}


@router.get("/rooms/{room_id}/ratings/mine", response_model=list[PlayerRatingSchema])
def get_my_ratings(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    room = find_room(db, room_id, current_user)
    rows = (
        db.query(PlayerRatingModel)
        .filter(
            PlayerRatingModel.rater_id == current_user.id,
            PlayerRatingModel.room_id == room.id,
        )
        .order_by(PlayerRatingModel.id)
        .all()
    )
    return [{"user_id": row.ratee_id, "stars": row.stars} for row in rows]


@router.get("/users/{user_id}/rating", response_model=UserRatingSchema)
def get_user_rating(user_id: int, db: Session = Depends(get_db)):
    load(db, UserModel, user_id)
    player_total, player_count = db.query(
        func.coalesce(func.sum(PlayerRatingModel.stars), 0), func.count(PlayerRatingModel.id)
    ).filter(PlayerRatingModel.ratee_id == user_id).one()
    # Host ratings given through attendance count as one rating each
    host_total, host_count = db.query(
        func.coalesce(func.sum(MembershipModel.rating), 0), func.count(MembershipModel.id)
    ).filter(
        MembershipModel.user_id == user_id,
        MembershipModel.room_id.is_not(None),
        MembershipModel.rating.is_not(None),
    ).one()

    count = player_count + host_count
    average = None
    if count:
        # Half-up on the exact fraction; float round() would turn 4.25 into 4.2
        average = float(
            (Decimal(player_total + host_total) / count).quantize(Decimal("0.1"), ROUND_HALF_UP)
        )
    return {"user_id": user_id, "average_rating": average, "rating_count": count}
