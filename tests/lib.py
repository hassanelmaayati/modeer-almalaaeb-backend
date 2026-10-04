from datetime import datetime, timedelta, timezone
import uuid

PREFIX = '/api/v1'
PASSWORD = 'TestPass123!'


def api(client, method, path, *, user=None, body=None, expected=200, **kwargs):
    headers = user['headers'] if user else {}
    response = client.request(method, PREFIX + path, headers=headers, json=body, **kwargs)
    assert response.status_code == expected, response.text
    return None if expected == 204 else response.json()


def future(hours=24):
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def room_body(sport_id, **changes):
    value = dict(sport_id=sport_id, title='Fixture activity', starts_at=future().isoformat(),
                 ends_at=future(25).isoformat(), capacity=4, district='capital',
                 public_area='Manama', venue_details='Private Court 7')
    value.update(changes)
    return value


class Factory:
    def __init__(self, db):
        self.db = db

    def persist(self, row):
        with self.db() as session:
            session.add(row)
            session.commit()
            session.refresh(row)
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def user(self, name=None, **changes):
        from models.user import UserModel
        name = name or 'player_' + uuid.uuid4().hex[:8]
        row = UserModel(user_name=name, email=name.lower().replace(' ', '') + '@example.test', district='capital', **changes)
        row.set_password(PASSWORD)
        data = self.persist(row)
        data['headers'] = {'Authorization': 'Bearer ' + row.generate_jwt()}
        data['plain_password'] = PASSWORD
        return data

    def sport(self, name='Swimming', **changes):
        from models.sport import SportModel
        return self.persist(SportModel(name=name, **changes))

    def group(self, owner, sport=None, **changes):
        from models.group import GroupModel
        sport = sport or self.sport()
        values = dict(owner_id=owner['id'], sports_id=sport['id'], name='Group ' + uuid.uuid4().hex[:6], description='Fixture group')
        values.update(changes)
        return self.persist(GroupModel(**values))

    def room(self, host, sport=None, **changes):
        from models.room import RoomModel
        sport = sport or self.sport()
        values = dict(host_id=host['id'], sport_id=sport['id'], title='Room ' + uuid.uuid4().hex[:6],
                      starts_at=future(), ends_at=future(25), capacity=4, district='capital',
                      public_area='Manama', venue_details='Private Court 7', slot_layout={})
        values.update(changes)
        return self.persist(RoomModel(**values))

    def member(self, user, *, room=None, group=None, cup=None, status='accepted', **changes):
        from models.membership import MembershipModel
        values = dict(user_id=user['id'], status=status, accepted=status == 'accepted', requested=False)
        for name, target in [('room_id', room), ('group_id', group), ('cup_id', cup)]:
            if target:
                values[name] = target['id']
        values.update(changes)
        return self.persist(MembershipModel(**values))

    def friend(self, first, second, status='accepted', **changes):
        from models.membership import MembershipModel
        values = dict(user_id=first['id'], other_user_id=second['id'], status=status, accepted=status == 'accepted', requested=True)
        values.update(changes)
        return self.persist(MembershipModel(**values))

    def cup(self, organizer, sport=None, **changes):
        from models.cup import CupModel
        sport = sport or self.sport('Football')
        values = dict(organizer_user_id=organizer['id'], sport_id=sport['id'], name='Fixture cup', rules='Fair play',
                      team_count=4, roster_limit=8, entries=[], fixtures=[])
        values.update(changes)
        return self.persist(CupModel(**values))

    def message(self, sender, *, room=None, group=None, recipient=None, body='Fixture message', **changes):
        from models.message import MessageModel
        values = dict(sender_id=sender['id'], body=body, client_request_id=uuid.uuid4())
        if room:
            values.update(room_id=room['id'], type='room')
        elif group:
            values.update(group_id=group['id'], type='group')
        else:
            values.update(recipient_id=recipient['id'], type='direct')
        values.update(changes)
        return self.persist(MessageModel(**values))
