from datetime import datetime, timedelta, timezone

from models.room import RoomModel

# Capacities match the sport formats in sports_data.py
def build_rooms():
    now = datetime.now(timezone.utc)
    return [
        RoomModel(
            host_id=1,
            sport_id=1,
            title="Friday 5-a-side",
            description="Friendly football match",
            difficulty="beginners",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            capacity=10,
            district="capital",
            public_area="Manama",
            venue_details="Pitch 3, Bahrain Sports Hall",
        ),
        RoomModel(
            host_id=2,
            sport_id=2,
            title="Basketball 3v3",
            difficulty="medium",
            starts_at=now + timedelta(days=2),
            ends_at=now + timedelta(days=2, hours=2),
            capacity=6,
            district="southern",
            public_area="Riffa",
            venue_details="Outdoor court behind the mall",
        ),
        # Group-only room, owned by the host of group 3
        RoomModel(
            host_id=3,
            sport_id=3,
            group_id=3,
            title="Tennis doubles (group only)",
            difficulty="advanced",
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=3, hours=1),
            capacity=4,
            visibility="group",
            district="muharraq",
            public_area="Muharraq",
            venue_details="Court 2",
        ),
        # Swimming has no formats, so any capacity is accepted
        RoomModel(
            host_id=4,
            sport_id=4,
            title="Morning swim",
            starts_at=now + timedelta(days=4),
            ends_at=now + timedelta(days=4, hours=1),
            capacity=8,
            district="capital",
            public_area="Juffair",
            distance_km=1.5,
            pace_notes="Easy pace",
        ),
    ]


rooms_list = build_rooms()
