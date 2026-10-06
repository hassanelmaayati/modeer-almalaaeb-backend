import math
import random
from datetime import datetime, timezone
from typing import List, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

# DB
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified
from database import get_db

# Models
from models.cup import CupModel, CUP_FORMATS, NO_CUP_SPORTS
from models.group import GroupModel
from models.sport import SportModel
from models.user import UserModel

# Serializers
from serializers.cup import (
    CupSchema,
    CreateCupSchema,
    UpdateCupSchema,
    FixtureResultSchema,
    RaceResultSchema,
    CreateEntrySchema,
    UpdateEntrySchema,
)

from dependencies.get_current_user import get_current_user
from dependencies.get_optional_user import get_optional_user
from services.changes import change_events
from services.memberships import commit
from services.realtime import queue_events

router = APIRouter(tags=["Cups Management"])

DETAIL_FIELDS = (
    "name",
    "rules",
    "team_count",
    "roster_limit",
    "registration_closes_at",
)
REQUIRED_FIELDS = ("name", "rules", "team_count", "roster_limit")
NEXT_STATUS = {"draft": "registration", "registration": "published"}


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def find_cup(db: Session, cup_id: int, user: UserModel | None, lock=False):
    query = db.query(CupModel).filter(CupModel.id == cup_id)
    if lock:
        # Serializes concurrent changes to the same cup's JSON data on PostgreSQL
        query = query.with_for_update()
    cup = query.first()

    # Drafts are private to their organizer
    if not cup or (
        cup.status == "draft" and (not user or user.id != cup.organizer_user_id)
    ):
        raise HTTPException(status_code=404, detail="Cup not found")
    return cup


def check_organizer(cup: CupModel, user: UserModel):
    if cup.organizer_user_id != user.id:
        raise HTTPException(
            status_code=403, detail="Only the cup organizer can do this"
        )


def check_revision(cup: CupModel, revision: int | None):
    if revision is not None and revision != cup.revision:
        raise HTTPException(
            status_code=409,
            detail="This cup was changed by someone else, reload and try again",
        )


def check_future(closes_at: datetime | None):
    if closes_at is not None and closes_at <= utc_now():
        raise HTTPException(
            status_code=400, detail="Registration must close in the future"
        )


def cup_format_for(sport: SportModel):
    sport_name = sport.name.strip().lower()
    if sport_name in NO_CUP_SPORTS:
        raise HTTPException(status_code=400, detail=NO_CUP_SPORTS[sport_name])

    cup_format = CUP_FORMATS.get(sport_name)
    if not cup_format:
        raise HTTPException(
            status_code=400, detail=f"Cups are not available for {sport.name} yet"
        )
    return cup_format


def check_team_count(cup_format: str, team_count: int):
    # A knockout bracket halves the field every round, so it needs 4, 8 or 16
    # teams; races pair nobody, so any field size from 2 works
    if cup_format == "knockout" and team_count not in (4, 8, 16):
        raise HTTPException(
            status_code=400, detail="Knockout cups need 4, 8 or 16 teams"
        )


def save(db: Session, cup: CupModel, background_tasks, actor_id):
    cup.revision += 1
    flag_modified(cup, "entries")
    flag_modified(cup, "fixtures")
    events = change_events(db, {"type": "cup", "id": cup.id}, "cup.updated",
                          "A cup you participate in was updated", actor_id)
    commit(db)
    db.refresh(cup)
    queue_events(background_tasks, events)
    return cup


def accepted_entries(cup: CupModel):
    return [entry for entry in cup.entries if entry["status"] == "accepted"]


def draw_fixtures(cup: CupModel):
    # Random round-one draw; later rounds are filled as winners advance
    group_ids = [entry["group_id"] for entry in accepted_entries(cup)]
    random.shuffle(group_ids)

    fixtures = []
    rounds = int(math.log2(cup.team_count))
    for round_number in range(1, rounds + 1):
        match_count = cup.team_count // 2**round_number
        for match_number in range(1, match_count + 1):
            fixture = {
                "id": f"R{round_number}-M{match_number}",
                "round": round_number,
                "match": match_number,
                "home_group_id": None,
                "away_group_id": None,
                "home_score": None,
                "away_score": None,
                "winner_group_id": None,
            }
            if round_number == 1:
                fixture["home_group_id"] = group_ids[2 * match_number - 2]
                fixture["away_group_id"] = group_ids[2 * match_number - 1]
            fixtures.append(fixture)
    return fixtures


def record_result(cup: CupModel, result: FixtureResultSchema):
    fixtures = [dict(fixture) for fixture in cup.fixtures]
    fixture = next((f for f in fixtures if f["id"] == result.fixture_id), None)
    if not fixture:
        raise HTTPException(status_code=404, detail="Fixture not found")

    if fixture["home_group_id"] is None or fixture["away_group_id"] is None:
        raise HTTPException(
            status_code=409, detail="Both teams for this fixture are not known yet"
        )
    if fixture["winner_group_id"] is not None:
        raise HTTPException(
            status_code=409, detail="A result is already recorded for this fixture"
        )

    teams = (fixture["home_group_id"], fixture["away_group_id"])
    if result.home_score > result.away_score:
        winner = fixture["home_group_id"]
    elif result.away_score > result.home_score:
        winner = fixture["away_group_id"]
    elif result.winner_group_id in teams:
        winner = result.winner_group_id
    else:
        raise HTTPException(
            status_code=400,
            detail="A drawn knockout match needs winner_group_id from one of its teams",
        )

    if result.winner_group_id is not None and result.winner_group_id != winner:
        raise HTTPException(
            status_code=400, detail="winner_group_id does not match the score"
        )

    fixture["home_score"] = result.home_score
    fixture["away_score"] = result.away_score
    fixture["winner_group_id"] = winner

    final_round = int(math.log2(cup.team_count))
    if fixture["round"] == final_round:
        cup.status = "completed"
    else:
        next_id = f"R{fixture['round'] + 1}-M{math.ceil(fixture['match'] / 2)}"
        next_fixture = next(f for f in fixtures if f["id"] == next_id)
        side = "home_group_id" if fixture["match"] % 2 == 1 else "away_group_id"
        next_fixture[side] = winner

    cup.fixtures = fixtures


def record_race_results(cup: CupModel, results: List[RaceResultSchema]):
    entries = [dict(entry) for entry in cup.entries]
    accepted = {e["group_id"]: e for e in entries if e["status"] == "accepted"}

    group_ids = [result.group_id for result in results]
    if len(group_ids) != len(set(group_ids)):
        raise HTTPException(
            status_code=400, detail="Each entrant can only appear once in race_results"
        )

    for result in results:
        entry = accepted.get(result.group_id)
        if not entry:
            raise HTTPException(
                status_code=400,
                detail=f"Group {result.group_id} is not an accepted entrant of this cup",
            )
        entry["finish_time_seconds"] = result.finish_time_seconds
        entry["position"] = result.position
        entry["did_not_finish"] = result.did_not_finish

    timed = [e for e in accepted.values() if e.get("finish_time_seconds") is not None]
    placed = [
        e
        for e in accepted.values()
        if e.get("finish_time_seconds") is None and e.get("position") is not None
    ]
    # Times and hand-entered positions cannot be ranked against each other
    if timed and placed:
        raise HTTPException(
            status_code=400,
            detail="Record times for every finisher or positions for every finisher, not a mix",
        )

    # Rank by time; equal times share a position (1, 1, 3)
    timed.sort(key=lambda e: e["finish_time_seconds"])
    for index, entry in enumerate(timed):
        if (
            index
            and entry["finish_time_seconds"] == timed[index - 1]["finish_time_seconds"]
        ):
            entry["position"] = timed[index - 1]["position"]
        else:
            entry["position"] = index + 1

    cup.entries = entries

    # The race is over once every accepted entrant has a position or a DNF
    if all(
        e.get("position") is not None or e.get("did_not_finish")
        for e in accepted.values()
    ):
        cup.status = "completed"


@router.get("/cups", response_model=List[CupSchema])
def get_cups(
    status: Literal["draft", "registration", "published", "completed"] | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: UserModel | None = Depends(get_optional_user),
):
    # Load organizer and sport (used by format) with the cups instead of per row
    query = db.query(CupModel).options(
        joinedload(CupModel.organizer), joinedload(CupModel.sport)
    )

    # Other people's drafts stay hidden
    if current_user:
        query = query.filter(
            or_(
                CupModel.status != "draft",
                CupModel.organizer_user_id == current_user.id,
            )
        )
    else:
        query = query.filter(CupModel.status != "draft")

    if status:
        query = query.filter(CupModel.status == status)

    return (
        query.order_by(CupModel.created_at.desc(), CupModel.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.get("/cups/{cup_id}", response_model=CupSchema)
def get_cup(
    cup_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel | None = Depends(get_optional_user),
):
    return find_cup(db, cup_id, current_user)


@router.post("/cups", response_model=CupSchema, status_code=201)
def create_cup(
    cup: CreateCupSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    sport = db.query(SportModel).filter(SportModel.id == cup.sport_id).first()
    if not sport:
        raise HTTPException(status_code=404, detail="Sport not found")

    check_team_count(cup_format_for(sport), cup.team_count)
    check_future(cup.registration_closes_at)

    new_cup = CupModel(
        **cup.model_dump(),
        organizer_user_id=current_user.id,
        entries=[],
        fixtures=[],
    )
    db.add(new_cup)
    db.flush()
    events = change_events(db, {"type": "cup", "id": new_cup.id}, "cup.created",
                          "A cup was created", current_user.id, notify=False)
    commit(db)
    db.refresh(new_cup)
    queue_events(background_tasks, events)
    return new_cup


@router.patch("/cups/{cup_id}", response_model=CupSchema)
def update_cup(
    cup_id: int,
    cup: UpdateCupSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_cup = find_cup(db, cup_id, current_user, lock=True)
    check_organizer(db_cup, current_user)
    check_revision(db_cup, cup.revision)

    details = cup.model_dump(exclude_unset=True, include=set(DETAIL_FIELDS))
    if details:
        if db_cup.status not in ("draft", "registration"):
            raise HTTPException(
                status_code=409, detail="Cup details are locked after publishing"
            )
        for key in REQUIRED_FIELDS:
            if key in details and details[key] is None:
                raise HTTPException(status_code=422, detail=f"{key} cannot be empty")
        if "team_count" in details:
            check_team_count(db_cup.format, details["team_count"])
        if details.get("team_count", db_cup.team_count) < len(accepted_entries(db_cup)):
            raise HTTPException(
                status_code=409,
                detail="team_count cannot be lower than the accepted entries",
            )
        # Entries compare against the close time, so an open registration needs one
        if (
            "registration_closes_at" in details
            and details["registration_closes_at"] is None
            and db_cup.status == "registration"
        ):
            raise HTTPException(
                status_code=400,
                detail="Registration close time is required while registration is open",
            )
        check_future(details.get("registration_closes_at"))
        for key, value in details.items():
            setattr(db_cup, key, value)

    if cup.status and cup.status != db_cup.status:
        if NEXT_STATUS.get(db_cup.status) != cup.status:
            raise HTTPException(
                status_code=409,
                detail=f"A {db_cup.status} cup cannot move to {cup.status}",
            )

        if cup.status == "registration":
            if db_cup.registration_closes_at is None:
                raise HTTPException(
                    status_code=409,
                    detail="Set registration_closes_at before opening registration",
                )
            check_future(db_cup.registration_closes_at)

        if cup.status == "published":
            accepted_count = len(accepted_entries(db_cup))
            if db_cup.format == "knockout":
                # Every bracket slot must be filled before the draw
                if accepted_count != db_cup.team_count:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Publishing needs exactly {db_cup.team_count} accepted teams",
                    )
                db_cup.fixtures = draw_fixtures(db_cup)
            elif accepted_count < 2:
                # A race needs at least two entrants; everyone starts together,
                # so nobody is paired and the fixtures stay empty
                raise HTTPException(
                    status_code=409,
                    detail="Publishing a race needs at least 2 accepted entrants",
                )
            db_cup.rosters_locked_at = utc_now()

        db_cup.status = cup.status

    if cup.result:
        # Races have no fixtures to score; they are ranked by finishing results
        if db_cup.format != "knockout":
            raise HTTPException(
                status_code=400,
                detail="This is a race cup, send race_results instead of result",
            )
        if db_cup.status != "published":
            raise HTTPException(
                status_code=409, detail="Results can only be recorded once published"
            )
        record_result(db_cup, cup.result)

    if cup.race_results:
        # Knockout cups are decided match by match through result instead
        if db_cup.format != "race":
            raise HTTPException(
                status_code=400,
                detail="This is a knockout cup, send result for one fixture instead of race_results",
            )
        if db_cup.status != "published":
            raise HTTPException(
                status_code=409, detail="Results can only be recorded once published"
            )
        record_race_results(db_cup, cup.race_results)

    return save(db, db_cup, background_tasks, current_user.id)


@router.delete("/cups/{cup_id}", status_code=204)
def delete_cup(
    cup_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_cup = find_cup(db, cup_id, current_user, lock=True)
    check_organizer(db_cup, current_user)

    if db_cup.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft cups can be deleted")

    db.delete(db_cup)
    commit(db)
    return None


@router.post("/cups/{cup_id}/entries", response_model=CupSchema, status_code=201)
def create_entry(
    cup_id: int,
    entry: CreateEntrySchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_cup = find_cup(db, cup_id, current_user, lock=True)
    check_revision(db_cup, entry.revision)

    if db_cup.status != "registration":
        raise HTTPException(status_code=409, detail="Registration is not open")
    # A missing close time counts as closed rather than crashing the comparison
    if db_cup.registration_closes_at is None or db_cup.registration_closes_at <= utc_now():
        raise HTTPException(status_code=409, detail="Registration has closed")

    group = db.query(GroupModel).filter(GroupModel.id == entry.group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Only the group owner can enter this team"
        )

    # A group is formed for one sport, so it only enters cups of that sport
    if group.sports_id != db_cup.sport_id:
        raise HTTPException(
            status_code=400, detail="This group plays a different sport than this cup"
        )

    entries = [dict(e) for e in db_cup.entries if e["group_id"] != group.id]
    if len(entries) != len(db_cup.entries):
        previous = next(e for e in db_cup.entries if e["group_id"] == group.id)
        if previous["status"] in ("pending", "accepted"):
            raise HTTPException(status_code=409, detail="This team is already entered")

    # Snapshot of the team at entry time. Entrants are groups in every format:
    # a solo runner enters a race through a one-person group, which keeps a
    # single entry flow and the existing /entries/{group_id} endpoints
    entries.append(
        {
            "group_id": group.id,
            "group_name": group.name,
            "owner_user_id": group.owner_id,
            "status": "pending",
            "entered_at": utc_now().isoformat(),
        }
    )
    db_cup.entries = entries
    return save(db, db_cup, background_tasks, current_user.id)


@router.put("/cups/{cup_id}/entries/{group_id}", response_model=CupSchema)
def update_entry(
    cup_id: int,
    group_id: int,
    entry: UpdateEntrySchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user),
):
    db_cup = find_cup(db, cup_id, current_user, lock=True)
    check_revision(db_cup, entry.revision)

    entries = [dict(e) for e in db_cup.entries]
    db_entry = next((e for e in entries if e["group_id"] == group_id), None)
    if not db_entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if db_cup.status != "registration":
        raise HTTPException(
            status_code=409, detail="Entries can only change while registration is open"
        )

    if entry.status == "withdrawn":
        group = db.query(GroupModel).filter(GroupModel.id == group_id).first()
        owner_id = group.owner_id if group else db_entry["owner_user_id"]
        if owner_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="Only the group owner can withdraw this team"
            )
        if db_entry["status"] == "withdrawn":
            raise HTTPException(
                status_code=409, detail="This team has already withdrawn"
            )
    else:
        check_organizer(db_cup, current_user)
        if db_entry["status"] == "withdrawn":
            raise HTTPException(status_code=409, detail="This team has withdrawn")
        if (
            entry.status == "accepted"
            and db_entry["status"] != "accepted"
            and len(accepted_entries(db_cup)) >= db_cup.team_count
        ):
            raise HTTPException(status_code=409, detail="All team places are taken")

    db_entry["status"] = entry.status
    db_cup.entries = entries
    return save(db, db_cup, background_tasks, current_user.id)
