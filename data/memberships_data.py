from models.membership import MembershipModel


def build_memberships():
    return [
        # Friends: user1 <-> user2 accepted, user1 -> user3 pending
        MembershipModel(
            user_id=1, other_user_id=2, status="accepted", requested=True, accepted=True
        ),
        MembershipModel(
            user_id=1, other_user_id=3, status="pending", requested=True, accepted=False
        ),
        # Group 1 (owner user1): user2 accepted, user3 invited
        MembershipModel(
            user_id=2, group_id=1, status="accepted", requested=False, accepted=True
        ),
        MembershipModel(
            user_id=3, group_id=1, status="pending", requested=False, accepted=False
        ),
        # Group 4 (owner user4): user1 accepted
        MembershipModel(
            user_id=1, group_id=4, status="accepted", requested=False, accepted=True
        ),
        # Cup 1 roster: user2 invited through group 1
        MembershipModel(
            user_id=2,
            group_id=1,
            cup_id=1,
            status="pending",
            requested=False,
            accepted=False,
        ),
        # Room 1: user2 asked to join, user3 is already in slot A1
        MembershipModel(
            user_id=2, room_id=1, status="pending", requested=True, accepted=False
        ),
        MembershipModel(
            user_id=3,
            room_id=1,
            status="accepted",
            position="A1",
            requested=True,
            accepted=True,
        ),
    ]
