"""Host hand-over: a manual transfer, and automatic promotion when the host stays away.

Presence is the host's open realtime socket, tracked in memory by the hub. A
started room whose host has no socket gets host_away_since (saved, so a restart
does not reset a long wait). After the grace period, the player who was admitted
first and is connected right now takes over. Only one instance runs this.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from config.environment import HOST_AWAY_GRACE_SECONDS
from models.base import utc_now
from models.membership import MembershipModel
from models.room import RoomModel
from models.user import UserModel
from services import realtime
from services.chat_access import room_user_ids
from services.messages import create_system_message, message_events
from services.notifications import notify_users
from services.realtime import user_event

logger = logging.getLogger(__name__)

HOST_AWAY_GRACE = timedelta(seconds=HOST_AWAY_GRACE_SECONDS)
# After a restart nobody is connected yet, so nothing changes for this long
BOOT_GRACE_SECONDS = 90
SWEEP_INTERVAL_SECONDS = 30


def transfer_host(db: Session, room: RoomModel, new_host_id: int, *, actor_id: int | None) -> list[dict]:
    """Make new_host_id the host. The caller holds the room lock and commits afterwards.

    actor_id is the person who asked (no notice for them), or None for an automatic promotion.
    """
    old_host_id = room.host_id
    # The old host stays as a player, so chat, venue access and ratings keep working for them
    old_row = db.query(MembershipModel).filter(
        MembershipModel.room_id == room.id, MembershipModel.user_id == old_host_id
    ).first()
    if old_row is None:
        old_row = MembershipModel(user_id=old_host_id, room_id=room.id, requested=False)
        db.add(old_row)
    old_row.status, old_row.accepted, old_row.position = "accepted", True, None
    old_row.accepted_at = utc_now()

    room.host_id = new_host_id
    room.host_generation += 1
    room.revision += 1
    room.host_away_since = None
    db.flush()

    name = db.get(UserModel, new_host_id).user_name
    note = f"The host changed: {name} is now the host" + (" (the previous host was away)" if actor_id is None else "")
    system_message = create_system_message(db, room.id, note)

    ids = set(room_user_ids(db, room.id))
    ids.update(row.user_id for row in db.query(MembershipModel.user_id).filter(
        MembershipModel.room_id == room.id, MembershipModel.status == "pending"))
    events = [
        user_event(ids, {"type": "room.updated", "room_id": room.id}),
        user_event(ids, {"type": "room.host_changed", "room_id": room.id,
                         "host_id": new_host_id, "host_generation": room.host_generation}),
    ]
    events += notify_users(db, ids, "room.host_changed", {"type": "room", "id": room.id},
                           "The host of a room you joined changed", exclude_user_id=actor_id)
    return events + message_events(db, system_message)


def eligible_players(db: Session, room: RoomModel):
    """Accepted players who could host, longest-admitted first (unknown admission times last)."""
    return (
        db.query(MembershipModel)
        .filter(
            MembershipModel.room_id == room.id,
            MembershipModel.status == "accepted",
            MembershipModel.user_id != room.host_id,
            or_(MembershipModel.attendance.is_(None), MembershipModel.attendance != "no_show"),
        )
        .order_by(MembershipModel.accepted_at.asc().nulls_last(), MembershipModel.id)
        .all()
    )


def promote(db: Session, room_id: int, expected_host_id: int, is_online: Callable[[int], bool],
            *, now: datetime, grace: timedelta) -> list[dict]:
    # Everything is checked again under the room lock, because the host may have
    # come back, the room may have ended, or someone may have transferred it meanwhile
    room = db.query(RoomModel).filter(RoomModel.id == room_id).with_for_update().populate_existing().first()
    if (room is None or room.status != "started" or room.host_id != expected_host_id
            or room.host_away_since is None or now - room.host_away_since < grace):
        return []
    if is_online(room.host_id):
        room.host_away_since = None
        return []
    # Promoting someone who is offline would not help anyone, so only connected players count
    candidate = next((row for row in eligible_players(db, room) if is_online(row.user_id)), None)
    if candidate is None:
        return []
    return transfer_host(db, room, candidate.user_id, actor_id=None)


def sweep(db: Session, online_ids: set[int], is_online: Callable[[int], bool], *, now: datetime,
          boot_grace_over: bool, grace: timedelta | None = None) -> list[dict]:
    """One pass over started rooms; returns the realtime events to send after the commit."""
    grace = HOST_AWAY_GRACE if grace is None else grace
    events: list[dict] = []
    for room in db.query(RoomModel).filter(RoomModel.status == "started").all():
        if room.host_id in online_ids:
            if room.host_away_since is not None:
                room.host_away_since = None
            continue
        if not boot_grace_over:
            continue
        if room.host_away_since is None:
            room.host_away_since = now
        elif now - room.host_away_since >= grace:
            events += promote(db, room.id, room.host_id, is_online, now=now, grace=grace)
    db.commit()
    return events


def sweep_in_thread(session_factory, online_ids, is_online, boot_grace_over: bool) -> list[dict]:
    db = session_factory()
    try:
        return sweep(db, online_ids, is_online, now=utc_now(), boot_grace_over=boot_grace_over)
    finally:
        db.close()


async def host_presence_loop(interval: float = SWEEP_INTERVAL_SECONDS, session_factory=None) -> None:
    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    started = time.monotonic()
    while True:
        try:
            hub = realtime.realtime_hub
            events = await asyncio.to_thread(
                sweep_in_thread, session_factory, hub.online_user_ids(),
                lambda user_id: user_id in hub.online_user_ids(),
                time.monotonic() - started >= BOOT_GRACE_SECONDS,
            )
            await realtime.send_events(events)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Host presence pass failed")
        await asyncio.sleep(interval)
