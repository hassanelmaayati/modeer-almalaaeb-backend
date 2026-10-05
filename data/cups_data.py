from datetime import datetime, timedelta, timezone
from models.cup import CupModel

now = datetime.now(timezone.utc).replace(tzinfo=None)

cups_list = [
    CupModel(
        organizer_user_id=1,
        sport_id=1,
        name="Bahrain Summer Cup",
        rules="Five-a-side, two 20-minute halves. Level games go to penalties.",
        team_count=4,
        roster_limit=8,
        status="draft",
        entries=[],
        fixtures=[],
    ),
    CupModel(
        organizer_user_id=2,
        sport_id=1,
        name="Manama Friday Cup",
        rules="Seven-a-side, two 25-minute halves. Level games go to penalties.",
        team_count=4,
        roster_limit=10,
        status="registration",
        registration_closes_at=now + timedelta(days=14),
        entries=[
            {
                "group_id": 1,
                "group_name": "Group 1",
                "owner_user_id": 1,
                "status": "pending",
                "entered_at": now.isoformat(),
            }
        ],
        fixtures=[],
    ),
    CupModel(
        organizer_user_id=3,
        # id 4 is Swimming, a race format sport
        sport_id=4,
        name="Seef Sunrise 10K",
        rules="10 km road race. Everyone starts together; ranked by finishing time.",
        team_count=40,
        roster_limit=1,
        status="registration",
        registration_closes_at=now + timedelta(days=21),
        entries=[],
        fixtures=[],
    ),
]
