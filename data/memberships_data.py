from models.membership import MembershipModel


def _member(**fields):
    cols = MembershipModel.__table__.columns.keys()
    return MembershipModel(**fields) if all(k in cols for k in fields) else None


memberships_list = [
    # Friends: user1 <-> user2 accepted, user1 -> user3 pending
    _member(
        user_id=1, other_user_id=2, status="accepted", requested=True, accepted=True
    ),
    _member(
        user_id=1, other_user_id=3, status="pending", requested=True, accepted=False
    ),
    # Group 1 (owner user1): user2 accepted, user3 invited
    _member(user_id=2, group_id=1, status="accepted", requested=False, accepted=True),
    _member(user_id=3, group_id=1, status="pending", requested=False, accepted=False),
    # Group 4 (owner user4): user1 accepted
    _member(user_id=1, group_id=4, status="accepted", requested=False, accepted=True),
    # Cup 1 roster: user2 invited through group 1
    _member(
        user_id=2,
        group_id=1,
        cup_id=1,
        status="pending",
        requested=False,
        accepted=False,
    ),
    # Room 1: user2 asked to join, user3 is already in slot A1
    _member(user_id=2, room_id=1, status="pending", requested=True, accepted=False),
    _member(
        user_id=3,
        room_id=1,
        status="accepted",
        position="A1",
        requested=True,
        accepted=True,
    ),
]

memberships_list = [m for m in memberships_list if m is not None]
