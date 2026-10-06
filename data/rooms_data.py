from datetime import datetime, timedelta, timezone

from models.room import RoomModel, make_point

# Capacities match the sport formats in sports_data.py.
# users and groups: the seeded rows in order; sports: sport id by name
def build_rooms(users, sports, groups):
    now = datetime.now(timezone.utc)
    return [
        RoomModel(
            host_id=users[0].id,
            sport_id=sports["Football"],
            title="Friday 5-a-side",
            description="Friendly football match",
            notes="Bring a light and a dark shirt.",
            difficulty="beginners",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            capacity=10,
            district="capital",
            area="Manama",
            venue_point=make_point(26.2285, 50.5860),
            venue_notes="Pitch 3, Bahrain Sports Hall",
        ),
        RoomModel(
            host_id=users[1].id,
            sport_id=sports["Basketball"],
            title="Basketball 3v3",
            difficulty="medium",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=2),
            capacity=6,
            district="southern",
            area="Riffa",
            venue_point=make_point(26.1300, 50.5550),
            venue_notes="Outdoor court behind the mall",
        ),
        # Group-only room, owned by the host of group 3 (a Padel group)
        RoomModel(
            host_id=users[2].id,
            sport_id=sports["Padel"],
            group_id=groups[2].id,
            title="Padel doubles (group only)",
            difficulty="advanced",
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=3, hours=1),
            capacity=4,
            visibility="group",
            district="muharraq",
            area="Muharraq",
            venue_point=make_point(26.2572, 50.6119),
            venue_notes="Court 2",
        ),
        # Swimming has no formats, so any capacity is accepted
        RoomModel(
            host_id=users[3].id,
            sport_id=sports["Swimming"],
            title="Morning swim",
            starts_at=now + timedelta(days=4),
            ends_at=now + timedelta(days=4, hours=1),
            capacity=8,
            district="capital",
            area="Juffair",
            distance_km=1.5,
            pace_notes="Easy pace",
        ),
    ]

