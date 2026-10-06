from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from models.cup import CupModel
from models.membership import MembershipModel
from models.notification import NotificationModel
from tests.lib import api, future


def cup_body(sport, **changes):
    return dict(sport_id=sport['id'], name='Weekend cup', rules='Fair play', team_count=4,
                roster_limit=8, registration_closes_at=future().isoformat(), **changes)


def revision(client, cup, user=None):
    # Cup writes must send the current revision; read it fresh between steps
    return api(client, 'GET', f"/cups/{cup['id']}", user=user)['revision']


def registration(client, factory, sport_name='Football', **changes):
    organizer, captain, sport = factory.user(), factory.user(), factory.sport(sport_name)
    body = cup_body(sport)
    body.update(changes)
    cup = api(client, 'POST', '/cups', user=organizer, body=body, expected=201)
    cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'status': 'registration', 'revision': cup['revision']})
    return cup, organizer, captain, sport


def enter(client, cup, group, captain):
    return api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain,
               body={'group_id': group['id'], 'revision': revision(client, cup)}, expected=201)


def accept_entry(client, cup, group, organizer):
    return api(client, 'PUT', f"/cups/{cup['id']}/entries/{group['id']}", user=organizer,
               body={'status': 'accepted', 'revision': revision(client, cup)})


def test_cup_create_privacy_edit_and_delete_persist(client, factory, db):
    organizer, outsider, sport = factory.user(), factory.user(), factory.sport('Football')
    cup = api(client, 'POST', '/cups', user=organizer, body=cup_body(sport), expected=201)
    assert (cup['format'], cup['status'], cup['entries'], cup['fixtures'], cup['revision']) == ('knockout', 'draft', [], [], 0)
    assert cup['organizer']['id'] == organizer['id']
    assert api(client, 'GET', '/cups') == []
    assert [item['id'] for item in api(client, 'GET', '/cups', user=organizer)] == [cup['id']]
    api(client, 'GET', f"/cups/{cup['id']}", user=outsider, expected=404)
    api(client, 'PATCH', f"/cups/{cup['id']}", user=outsider, body={'name': 'Hijacked', 'revision': 0}, expected=404)
    updated = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer,
                  body={'name': 'Renamed', 'revision': 0})
    assert updated['revision'] == 1
    with db() as session:
        row = session.get(CupModel, cup['id'])
        assert (row.name, row.organizer_user_id, row.status) == ('Renamed', organizer['id'], 'draft')
    response = client.delete(f"/api/v1/cups/{cup['id']}", headers=organizer['headers'])
    assert response.status_code == 204 and response.content == b''
    with db() as session:
        assert session.get(CupModel, cup['id']) is None


@pytest.mark.parametrize('sport_name,changes,status', [
    ('Football', {'team_count': 6}, 400), ('Walking', {}, 400), ('Chess', {}, 400),
    ('Football', {'team_count': 1}, 422), ('Football', {'roster_limit': 0}, 422),
    ('Football', {'name': ''}, 422), ('Football', {'registration_closes_at': '2020-01-01T00:00:00Z'}, 400),
])
def test_invalid_cup_never_persists(client, factory, db, sport_name, changes, status):
    organizer, sport = factory.user(), factory.sport(sport_name)
    body = cup_body(sport)
    body.update(changes)
    api(client, 'POST', '/cups', user=organizer, body=body, expected=status)
    with db() as session:
        assert session.query(CupModel).count() == 0
        assert session.query(NotificationModel).count() == 0


def test_cup_auth_missing_sport_and_status_validation(client, factory, db):
    organizer, sport = factory.user(), factory.sport('Football')
    api(client, 'POST', '/cups', body=cup_body(sport), expected=401)
    api(client, 'POST', '/cups', user=organizer, body=cup_body({'id': 999999}), expected=404)
    api(client, 'GET', '/cups?status=cancelled', expected=422)
    with db() as session:
        assert session.query(CupModel).count() == 0


def test_registration_and_entry_permissions_preserve_rejected_state(client, factory, db):
    cup, organizer, captain, sport = registration(client, factory)
    outsider = factory.user()
    group = factory.group(captain, sport)
    wrong_sport = factory.group(captain, factory.sport('Basketball'))
    current = cup['revision']
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=outsider, body={'group_id': group['id'], 'revision': current}, expected=403)
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain, body={'group_id': wrong_sport['id'], 'revision': current}, expected=400)
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain, body={'group_id': 999999, 'revision': current}, expected=404)
    api(client, 'PATCH', f"/cups/{cup['id']}", user=outsider, body={'name': 'Hijacked', 'revision': current}, expected=403)
    assert api(client, 'GET', f"/cups/{cup['id']}")['status'] == 'registration'
    with db() as session:
        assert session.get(CupModel, cup['id']).entries == []
        assert session.query(NotificationModel).count() == 0
    entered = enter(client, cup, group, captain)
    assert entered['entries'][0]['group_name'] == group['name']
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain,
        body={'group_id': group['id'], 'revision': revision(client, cup)}, expected=409)
    api(client, 'PUT', f"/cups/{cup['id']}/entries/{group['id']}", user=captain,
        body={'status': 'accepted', 'revision': revision(client, cup)}, expected=403)
    accept_entry(client, cup, group, organizer)
    withdrawn = api(client, 'PUT', f"/cups/{cup['id']}/entries/{group['id']}", user=captain,
                    body={'status': 'withdrawn', 'revision': revision(client, cup)})
    assert withdrawn['entries'][0]['status'] == 'withdrawn'
    with db() as session:
        assert session.get(CupModel, cup['id']).entries[0]['status'] == 'withdrawn'
    api(client, 'DELETE', f"/cups/{cup['id']}", user=organizer, expected=409)


def test_knockout_draw_winners_advance_and_final_completes(client, factory, db):
    cup, organizer, captain, sport = registration(client, factory)
    groups = [factory.group(captain, sport) for _ in range(4)]
    for group in groups:
        enter(client, cup, group, captain)
        accept_entry(client, cup, group, organizer)
    cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'status': 'published', 'revision': revision(client, cup)})
    assert cup['rosters_locked_at'] and len(cup['fixtures']) == 3
    assert {match[side] for match in cup['fixtures'][:2] for side in ('home_group_id', 'away_group_id')} == {group['id'] for group in groups}
    before = cup['revision']
    # The final's teams are not known yet (state, 409); a draw without a winner is bad input (400)
    for result, status in [({'fixture_id': 'R2-M1', 'home_score': 1, 'away_score': 0}, 409),
                           ({'fixture_id': 'R1-M1', 'home_score': 1, 'away_score': 1}, 400)]:
        api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'result': result, 'revision': before}, expected=status)
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'name': 'Too late', 'revision': before}, expected=409)
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer,
        body={'race_results': [{'group_id': groups[0]['id'], 'position': 1}], 'revision': before}, expected=400)
    with db() as session:
        row = session.get(CupModel, cup['id'])
        assert row.revision == before and all(match['winner_group_id'] is None for match in row.fixtures)
    winners = []
    for match in cup['fixtures'][:2]:
        winners.append(match['home_group_id'])
        cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer,
                  body={'result': {'fixture_id': match['id'], 'home_score': 2, 'away_score': 0},
                        'revision': cup['revision']})
    assert (cup['fixtures'][2]['home_group_id'], cup['fixtures'][2]['away_group_id']) == tuple(winners)
    cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer,
              body={'result': {'fixture_id': 'R2-M1', 'home_score': 0, 'away_score': 1},
                    'revision': cup['revision']})
    assert cup['status'] == 'completed' and cup['fixtures'][2]['winner_group_id'] == winners[1]
    with db() as session:
        assert session.get(CupModel, cup['id']).fixtures == cup['fixtures']
    assert [item['id'] for item in api(client, 'GET', '/cups?status=completed')] == [cup['id']]


def test_race_ties_and_dnf_persist_competition_rankings(client, factory, db):
    cup, organizer, captain, sport = registration(client, factory, 'Running')
    groups = [factory.group(captain, sport) for _ in range(4)]
    for group in groups:
        enter(client, cup, group, captain)
        accept_entry(client, cup, group, organizer)
    cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'status': 'published', 'revision': revision(client, cup)})
    assert cup['format'] == 'race' and cup['fixtures'] == []
    mixed = [{'group_id': groups[0]['id'], 'position': 1}, {'group_id': groups[1]['id'], 'finish_time_seconds': 60}]
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'race_results': mixed, 'revision': cup['revision']}, expected=400)
    duplicate = [{'group_id': groups[0]['id'], 'position': 1}] * 2
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'race_results': duplicate, 'revision': cup['revision']}, expected=400)
    results = [{'group_id': group['id'], 'finish_time_seconds': seconds} for group, seconds in zip(groups[:3], [1800, 1800, 1900])]
    results.append({'group_id': groups[3]['id'], 'did_not_finish': True})
    cup = api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'race_results': results, 'revision': cup['revision']})
    assert cup['status'] == 'completed'
    assert [entry['position'] for entry in cup['entries']] == [1, 1, 3, None]
    with db() as session:
        entries = session.get(CupModel, cup['id']).entries
        assert [entry['group_id'] for entry in entries] == [group['id'] for group in groups]
        assert [entry['position'] for entry in entries] == [1, 1, 3, None]
        assert [entry['finish_time_seconds'] for entry in entries] == [1800, 1800, 1900, None]
        assert [entry['did_not_finish'] for entry in entries] == [False, False, False, True]


def roster_setup(factory, count=2, **cup_changes):
    organizer, captain, sport = factory.user(), factory.user(), factory.sport('Football')
    group = factory.group(captain, sport)
    cup = factory.cup(organizer, sport, status='registration', registration_closes_at=future(),
        entries=[{'group_id': group['id'], 'group_name': group['name'], 'owner_user_id': captain['id'],
                  'status': 'accepted', 'entered_at': future().isoformat()}], **cup_changes)
    users = [factory.user() for _ in range(count)]
    for user in users:
        factory.member(user, group=group)
    return cup, group, captain, users


def test_roster_invitation_acceptance_departure_and_terminal_guard(client, factory, db):
    cup, group, captain, (player, other) = roster_setup(factory)
    invite = {'user_id': player['id'], 'group_id': group['id']}
    row = api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain, body=invite, expected=201)
    assert row['status'] == 'pending'
    api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain, body=invite, expected=409)
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=other, body={'status': 'accepted'}, expected=403)
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=player, body={'status': 'accepted'})
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=player, body={'status': 'left'})
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=player, body={'status': 'accepted'}, expected=403)
    with db() as session:
        persisted = session.get(MembershipModel, row['id'])
        assert (persisted.status, persisted.accepted) == ('left', False)


def test_roster_owner_removal_cannot_be_self_reversed(client, factory, db):
    cup, group, captain, (player,) = roster_setup(factory, count=1)
    row = api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain,
              body={'user_id': player['id'], 'group_id': group['id']}, expected=201)
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=captain, body={'status': 'removed'})
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=player, body={'status': 'accepted'}, expected=403)
    with db() as session:
        assert session.get(MembershipModel, row['id']).status == 'removed'


def test_roster_missing_cup_nonmember_and_closed_cup_never_write(client, factory, db):
    cup, group, captain, _ = roster_setup(factory)
    outsider = factory.user()
    body = {'user_id': outsider['id'], 'group_id': group['id']}
    api(client, 'POST', '/cups/999999/roster', user=captain, body=body, expected=404)
    api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain, body=body, expected=400)
    with db() as session:
        row = session.get(CupModel, cup['id'])
        row.status = 'published'
        session.commit()
    api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain, body=body, expected=409)
    with db() as session:
        assert session.query(MembershipModel).filter(MembershipModel.cup_id == cup['id']).count() == 0
        assert session.query(NotificationModel).count() == 0


def test_declined_team_entry_prevents_roster_acceptance(client, factory, db):
    cup, group, captain, (player,) = roster_setup(factory, count=1)
    row = api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain,
              body={'user_id': player['id'], 'group_id': group['id']}, expected=201)
    with db() as session:
        persisted = session.get(CupModel, cup['id'])
        persisted.entries = [{**entry, 'status': 'declined'} for entry in persisted.entries]
        session.commit()
        notices = session.query(NotificationModel).count()
    api(client, 'PATCH', f"/cups/{cup['id']}/roster/{player['id']}", user=player,
        body={'status': 'accepted'}, expected=409)
    with db() as session:
        persisted = session.get(MembershipModel, row['id'])
        assert (persisted.status, persisted.accepted) == ('pending', False)
        assert session.query(NotificationModel).count() == notices


def test_concurrent_roster_acceptance_cannot_exceed_capacity(client, factory, db):
    cup, group, captain, users = roster_setup(factory, roster_limit=1)
    for user in users:
        api(client, 'POST', f"/cups/{cup['id']}/roster", user=captain,
            body={'user_id': user['id'], 'group_id': group['id']}, expected=201)
    barrier = Barrier(2)
    def accept(user):
        barrier.wait(timeout=5)
        return client.patch(f"/api/v1/cups/{cup['id']}/roster/{user['id']}",
                            headers=user['headers'], json={'status': 'accepted'}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(accept, users))
    assert sorted(statuses) == [200, 409]
    with db() as session:
        assert session.query(MembershipModel).filter(MembershipModel.cup_id == cup['id'], MembershipModel.status == 'accepted').count() == 1


def test_concurrent_cup_edits_reject_stale_revision(client, factory, db):
    organizer, sport = factory.user(), factory.sport('Football')
    cup = factory.cup(organizer, sport)
    barrier = Barrier(2)
    def edit(name):
        barrier.wait(timeout=5)
        return client.patch(f"/api/v1/cups/{cup['id']}", headers=organizer['headers'],
                            json={'name': name, 'revision': 0}).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(edit, ['First edit', 'Second edit']))
    assert sorted(statuses) == [200, 409]
    with db() as session:
        row = session.get(CupModel, cup['id'])
        assert row.revision == 1 and row.name in ('First edit', 'Second edit')


def test_open_registration_cannot_clear_its_close_time(client, factory, db):
    organizer, captain, sport = factory.user(), factory.user(), factory.sport('Football')
    cup = factory.cup(organizer, sport, status='registration', registration_closes_at=future().replace(tzinfo=None))
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer,
        body={'registration_closes_at': None, 'revision': 0}, expected=400)
    draft = factory.cup(organizer, sport, registration_closes_at=future().replace(tzinfo=None))
    cleared = api(client, 'PATCH', f"/cups/{draft['id']}", user=organizer,
                  body={'registration_closes_at': None, 'revision': 0})
    assert cleared['registration_closes_at'] is None
    # A legacy registration row without a close time is treated as closed instead of a 500
    legacy = factory.cup(organizer, sport, status='registration', registration_closes_at=None)
    group = factory.group(captain, sport)
    api(client, 'POST', f"/cups/{legacy['id']}/entries", user=captain,
        body={'group_id': group['id'], 'revision': 0}, expected=409)
    with db() as session:
        assert session.get(CupModel, cup['id']).registration_closes_at is not None


def test_cup_writes_require_a_revision(client, factory, db):
    organizer, captain, sport = factory.user(), factory.user(), factory.sport('Football')
    group = factory.group(captain, sport)
    cup = factory.cup(organizer, sport, status='registration', registration_closes_at=future().replace(tzinfo=None),
        entries=[{'group_id': group['id'], 'group_name': group['name'], 'owner_user_id': captain['id'],
                  'status': 'pending', 'entered_at': future().isoformat()}])
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'name': 'No revision'}, expected=422)
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain, body={'group_id': group['id']}, expected=422)
    api(client, 'PUT', f"/cups/{cup['id']}/entries/{group['id']}", user=organizer, body={'status': 'accepted'}, expected=422)
    with db() as session:
        row = session.get(CupModel, cup['id'])
        assert (row.revision, row.name, row.entries[0]['status']) == (0, 'Fixture cup', 'pending')


def test_cup_list_pages_with_limit_and_offset(client, factory):
    organizer = factory.user()
    ids = [factory.cup(organizer, status='registration')['id'] for _ in range(3)]
    newest_first = list(reversed(ids))
    assert [cup['id'] for cup in api(client, 'GET', '/cups?limit=2')] == newest_first[:2]
    assert [cup['id'] for cup in api(client, 'GET', '/cups?limit=2&offset=2')] == newest_first[2:]
    for query in ('limit=0', 'limit=101', 'offset=-1'):
        api(client, 'GET', f'/cups?{query}', expected=422)


def test_roster_list_hides_drafts_and_pending_invites_from_others(client, factory):
    cup, group, captain, (player, invitee) = roster_setup(factory)
    factory.member(player, group=group, cup=cup)
    factory.member(invitee, group=group, cup=cup, status='pending')
    outsider = factory.user()
    def roster_users(user=None):
        return sorted(row['user_id'] for row in api(client, 'GET', f"/cups/{cup['id']}/roster", user=user))
    assert roster_users() == roster_users(outsider) == [player['id']]
    assert roster_users(invitee) == roster_users(captain) == sorted([player['id'], invitee['id']])
    draft = factory.cup(factory.user())
    api(client, 'GET', f"/cups/{draft['id']}/roster", expected=404)
    api(client, 'GET', f"/cups/{draft['id']}/roster", user=outsider, expected=404)
    api(client, 'GET', '/cups/999999/roster', expected=404)
