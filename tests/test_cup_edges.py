"""Tournament formats, input boundaries and bracket result edge cases."""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from controllers.cups import draw_fixtures, record_result
from models.cup import CUP_FORMATS, CupModel
from models.notification import NotificationModel
from serializers.cup import FixtureResultSchema, RaceResultSchema
from tests.lib import api, future


@pytest.mark.parametrize('sport_name,expected_format', list(CUP_FORMATS.items()))
def test_every_supported_sport_creates_the_canonical_cup_format(client, factory, sport_name, expected_format):
    organizer, sport = factory.user(), factory.sport(sport_name.upper())
    created = api(client, 'POST', '/cups', user=organizer, body={
        'sport_id': sport['id'], 'name': 'A supported cup', 'rules': 'Fair play',
        'team_count': 4 if expected_format == 'knockout' else 3, 'roster_limit': 1,
        'organizer_user_id': 99999, 'status': 'completed', 'entries': [{'group_id': 123}],
    }, expected=201)
    assert created['format'] == expected_format and created['status'] == 'draft'
    assert created['organizer_user_id'] == organizer['id'] and created['entries'] == [] and created['fixtures'] == []
    assert {'email', 'password', 'google_subject', 'token_version'}.isdisjoint(created['organizer'])


@pytest.mark.parametrize('sport_name,expected_format', [
    ('Walking', None), ('Marathon', 'race'), ('Cycling', 'race'), ('Handball', 'knockout'),
    ('Padel', 'knockout'), ('Running', 'race'), ('Swimming', 'race'), ('Kayak', 'race'),
    ('Billiards', 'knockout'),
])
def test_live_catalogue_cup_policy_and_format_capacity_guards(client, factory, db, sport_name, expected_format):
    organizer, sport = factory.user(), factory.sport(sport_name)
    payload = {'sport_id': sport['id'], 'name': sport_name + ' cup', 'rules': 'Fair play',
               'team_count': 4 if expected_format == 'knockout' else 3, 'roster_limit': 1}
    if expected_format is None:
        rejected = api(client, 'POST', '/cups', user=organizer, body=payload, expected=400)
        assert 'Walking is a social outing' in rejected['detail']
        with db() as session:
            assert session.query(CupModel).count() == 0 and session.query(NotificationModel).count() == 0
        return
    cup = api(client, 'POST', '/cups', user=organizer, body=payload, expected=201)
    assert cup['format'] == expected_format and cup['sport_id'] == sport['id'] and cup['status'] == 'draft'
    if expected_format == 'knockout':
        api(client, 'POST', '/cups', user=organizer, body={**payload, 'team_count': 3}, expected=400)
    else:
        api(client, 'POST', '/cups', user=organizer, body={**payload, 'team_count': 1}, expected=422)
    with db() as session:
        assert session.query(CupModel).count() == 1 and session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('field', ['name', 'rules', 'team_count', 'roster_limit'])
def test_required_cup_details_cannot_be_cleared_and_rejected_updates_leave_no_events(client, factory, db, field):
    organizer = factory.user()
    cup = factory.cup(organizer)
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={field: None, 'revision': 0}, expected=422)
    with db() as session:
        stored = session.get(CupModel, cup['id'])
        assert stored.revision == 0 and stored.name == cup['name']
        assert session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('old,new', [('draft', 'published'), ('registration', 'registration'), ('published', 'registration'), ('completed', 'published')])
def test_cup_status_transition_guard_persists_only_idempotent_registration(client, factory, db, old, new):
    organizer = factory.user()
    cup = factory.cup(organizer, status=old, registration_closes_at=future().replace(tzinfo=None))
    expected = 200 if old == new else 409
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={'status': new, 'revision': 0}, expected=expected)
    with db() as session:
        stored = session.get(CupModel, cup['id'])
        assert stored.status == old and stored.revision == (1 if expected == 200 else 0)


@pytest.mark.parametrize('team_count', [4, 8, 16])
def test_complete_brackets_contain_each_entrant_once_and_every_winner_advances(team_count):
    cup = SimpleNamespace(team_count=team_count, status='published', entries=[
        {'group_id': group_id, 'status': 'accepted'} for group_id in range(1, team_count + 1)
    ])
    cup.fixtures = draw_fixtures(cup)
    first_round = [fixture for fixture in cup.fixtures if fixture['round'] == 1]
    assert len(cup.fixtures) == team_count - 1 and len(first_round) == team_count // 2
    assert sorted(fixture[side] for fixture in first_round for side in ('home_group_id', 'away_group_id')) == list(range(1, team_count + 1))
    for original in list(cup.fixtures):
        fixture = next(item for item in cup.fixtures if item['id'] == original['id'])
        assert fixture['home_group_id'] is not None and fixture['away_group_id'] is not None
        winner = fixture['away_group_id']
        record_result(cup, FixtureResultSchema(fixture_id=fixture['id'], home_score=0, away_score=1))
        updated = next(item for item in cup.fixtures if item['id'] == fixture['id'])
        assert updated['winner_group_id'] == winner and updated['home_score'] == 0 and updated['away_score'] == 1
    assert cup.status == 'completed'
    assert all(fixture['winner_group_id'] is not None for fixture in cup.fixtures)


@pytest.mark.parametrize('problem,status', [('missing', 404), ('not-ready', 409), ('already-scored', 409), ('tie-no-winner', 400), ('tie-wrong-winner', 400), ('contradicted-winner', 400)])
def test_invalid_knockout_result_leaves_the_bracket_unchanged(problem, status):
    fixture = {'id': 'R2-M1', 'round': 2, 'match': 1, 'home_group_id': 1, 'away_group_id': 2,
               'home_score': None, 'away_score': None, 'winner_group_id': None}
    result = {'fixture_id': fixture['id'], 'home_score': 1, 'away_score': 0}
    if problem == 'missing': result['fixture_id'] = 'unknown'
    if problem == 'not-ready': fixture['away_group_id'] = None
    if problem == 'already-scored': fixture['winner_group_id'] = 1
    if problem.startswith('tie'):
        result['away_score'] = 1
        if problem == 'tie-wrong-winner': result['winner_group_id'] = 99
    if problem == 'contradicted-winner': result['winner_group_id'] = 2
    before = dict(fixture)
    cup = SimpleNamespace(team_count=4, status='published', fixtures=[fixture])
    with pytest.raises(HTTPException) as rejected:
        record_result(cup, FixtureResultSchema(**result))
    assert rejected.value.status_code == status
    assert cup.status == 'published' and cup.fixtures == [before]


def test_penalty_winner_breaks_a_tied_final():
    cup = SimpleNamespace(team_count=4, status='published', fixtures=[{
        'id': 'R2-M1', 'round': 2, 'match': 1, 'home_group_id': 1, 'away_group_id': 2,
        'home_score': None, 'away_score': None, 'winner_group_id': None,
    }])
    record_result(cup, FixtureResultSchema(fixture_id='R2-M1', home_score=2, away_score=2, winner_group_id=2))
    assert cup.status == 'completed' and cup.fixtures[0]['winner_group_id'] == 2


@pytest.mark.parametrize('outcomes', [
    {}, {'finish_time_seconds': 0}, {'finish_time_seconds': -1}, {'position': 0},
    {'position': 1, 'did_not_finish': True}, {'finish_time_seconds': 1, 'position': 1},
    {'finish_time_seconds': 1, 'did_not_finish': True},
    {'finish_time_seconds': float('inf')}, {'finish_time_seconds': float('nan')},
])
def test_invalid_race_outcomes_are_rejected_before_database_or_json_encoding(outcomes):
    with pytest.raises(ValidationError):
        RaceResultSchema(group_id=1, **outcomes)


@pytest.mark.parametrize('field', ['name', 'rules'])
def test_whitespace_cup_labels_are_rejected_without_writes(client, factory, db, field):
    organizer, sport = factory.user(), factory.sport('Football')
    body = {'sport_id': sport['id'], 'name': 'A cup', 'rules': 'Fair play', 'team_count': 4, 'roster_limit': 8, field: '   '}
    api(client, 'POST', '/cups', user=organizer, body=body, expected=422)
    with db() as session:
        assert session.query(CupModel).count() == 0 and session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('case', ['no-deadline', 'incomplete-bracket', 'single-race-entrant', 'shrink-capacity', 'early-knockout-result', 'early-race-result', 'race-with-fixture-result'])
def test_invalid_cup_publication_and_results_leave_all_rows_and_notices_unchanged(client, factory, db, case):
    organizer = factory.user()
    is_race = case in ('single-race-entrant', 'early-race-result', 'race-with-fixture-result')
    sport = factory.sport('Running' if is_race else 'Football')
    entries = [{'group_id': index, 'group_name': f'Team {index}', 'owner_user_id': organizer['id'],
                'status': 'accepted', 'entered_at': future().isoformat()} for index in range(1, 9)]
    if case != 'shrink-capacity':
        entries = entries[:1] if case == 'single-race-entrant' else []
    cup = factory.cup(organizer, sport, team_count=8 if case == 'shrink-capacity' else 4,
                      status='draft' if case == 'no-deadline' else 'registration',
                      registration_closes_at=None if case == 'no-deadline' else future().replace(tzinfo=None), entries=entries)
    change = {'status': 'registration'} if case == 'no-deadline' else {'status': 'published'}
    if case == 'shrink-capacity': change = {'team_count': 4}
    if case in ('early-knockout-result', 'race-with-fixture-result'):
        change = {'result': {'fixture_id': 'R1-M1', 'home_score': 1, 'away_score': 0}}
    if case == 'early-race-result': change = {'race_results': [{'group_id': 1, 'position': 1}]}
    # Only sending a fixture result to a race is bad input; the rest conflict with the cup's state
    expected = 400 if case == 'race-with-fixture-result' else 409
    api(client, 'PATCH', f"/cups/{cup['id']}", user=organizer, body={**change, 'revision': 0}, expected=expected)
    with db() as session:
        stored = session.get(CupModel, cup['id'])
        assert stored.status == cup['status'] and stored.team_count == cup['team_count']
        assert stored.entries == entries and stored.fixtures == [] and stored.revision == 0
        assert stored.rosters_locked_at is None and session.query(NotificationModel).count() == 0


@pytest.mark.parametrize('case,expected', [('closed-status', 409), ('closed-deadline', 409), ('stale-revision', 409)])
def test_cup_entry_creation_obeys_registration_and_revision_guards(client, factory, db, case, expected):
    organizer, captain, sport = factory.user(), factory.user(), factory.sport('Football')
    group = factory.group(captain, sport)
    cup = factory.cup(organizer, sport, status='published' if case == 'closed-status' else 'registration',
                      registration_closes_at=future(-1 if case == 'closed-deadline' else 1).replace(tzinfo=None))
    api(client, 'POST', f"/cups/{cup['id']}/entries", user=captain,
        body={'group_id': group['id'], 'revision': 99 if case == 'stale-revision' else 0}, expected=expected)
    with db() as session:
        assert session.get(CupModel, cup['id']).entries == [] and session.get(CupModel, cup['id']).revision == 0
        assert session.query(NotificationModel).count() == 0
