from datetime import datetime, timedelta, timezone

from models.cup import CupModel


# users and groups: the seeded rows in order; sports: sport id by name
def build_cups(users, sports, groups):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return [
        CupModel(
            organizer_user_id=users[0].id,
            sport_id=sports["Football"],
            name="Bahrain Summer Cup",
            rules="Five-a-side, two 20-minute halves. Level games go to penalties.",
            team_count=4,
            roster_limit=8,
            status="draft",
            entries=[],
            fixtures=[],
        ),
        CupModel(
            organizer_user_id=users[1].id,
            sport_id=sports["Football"],
            name="Manama Friday Cup",
            rules="Seven-a-side, two 25-minute halves. Level games go to penalties.",
            team_count=4,
            roster_limit=10,
            status="registration",
            registration_closes_at=now + timedelta(days=14),
            entries=[
                {
                    "group_id": groups[0].id,
                    "group_name": groups[0].name,
                    "owner_user_id": groups[0].owner_id,
                    "status": "pending",
                    "entered_at": now.isoformat(),
                }
            ],
            fixtures=[],
        ),
        # Swimming is a race: everyone starts together and is ranked by time
        CupModel(
            organizer_user_id=users[2].id,
            sport_id=sports["Swimming"],
            name="Juffair Open Water 1500m",
            rules="1500 m open-water swim. Everyone starts together; ranked by finishing time.",
            team_count=40,
            roster_limit=1,
            status="registration",
            registration_closes_at=now + timedelta(days=21),
            entries=[],
            fixtures=[],
        ),
    ]
