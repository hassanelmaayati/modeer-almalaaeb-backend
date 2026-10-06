import pytest

from models.room import RoomModel
from scripts.import_sports import import_sports
from tests.lib import api, room_body


def test_sports_are_exact_isolated_fixtures_and_missing_id_is_404(client,factory):
    first=factory.sport('Swimming',formats=[{'key':'four','capacity':4}])
    second=factory.sport('Football')
    assert [(item['id'],item['name']) for item in api(client,'GET','/sports')] == [(first['id'],'Swimming'),(second['id'],'Football')]
    assert api(client,'GET',f"/sports/{first['id']}")['name']=='Swimming'
    # The formats are exposed so clients can offer a format dropdown instead of a free capacity
    assert api(client,'GET',f"/sports/{first['id']}")['formats']==[{'key':'four','capacity':4}]
    assert api(client,'GET',f"/sports/{second['id']}")['formats'] is None
    api(client,'GET','/sports/987654',expected=404)


@pytest.mark.parametrize('name,cup_format', [('Football','knockout'),('Swimming','race'),('Walking',None),('Chess',None)])
def test_sports_expose_the_cup_format_used_by_cups(client,factory,name,cup_format):
    sport=factory.sport(name)
    assert api(client,'GET',f"/sports/{sport['id']}")['cup_format']==cup_format


@pytest.mark.parametrize('name', ['Padel', 'Swimming', 'Walking', 'Running', 'Cycling', 'Handball', 'Billiards', 'Kayak'])
def test_live_catalogue_additions_support_free_capacity_rooms_and_exact_discovery(client, factory, db, database_url, name):
    import_sports(database_url)
    catalogue = api(client, 'GET', '/sports')
    matches = [sport for sport in catalogue if sport['name'] == name]
    assert len(matches) == 1, f'{name} is missing from the offline production catalogue'
    sport = matches[0]
    assert sport['formats'] is None
    assert api(client, 'GET', f"/sports/{sport['id']}") == sport
    owner = factory.user()
    fields = dict(capacity=3, distance_km=12.5, pace_notes='Conversation pace', route_notes='Public route',
                  venue_location={'latitude': 26.2235, 'longitude': 50.5876}, venue_notes='Private meeting point')
    room = api(client, 'POST', '/rooms', user=owner, body=room_body(sport['id'], **fields), expected=201)
    assert room['sport_id'] == sport['id'] and room['capacity'] == 3
    assert room['distance_km'] == 12.5 and room['pace_notes'] == fields['pace_notes']
    assert room['route_notes'] == fields['route_notes'] and room['venue_notes'] == fields['venue_notes']
    football = next(item for item in catalogue if item['name'] == 'Football')
    unrelated = factory.room(owner, football, capacity=10)
    discovery = api(client, 'GET', '/rooms', params={'sport_id': sport['id']})
    assert [item['id'] for item in discovery] == [room['id']]
    assert {'venue_location', 'venue_notes'}.isdisjoint(discovery[0])
    assert discovery[0]['distance_km'] == 12.5 and unrelated['id'] != room['id']
    updated = api(client, 'PUT', f"/rooms/{room['id']}", user=owner, body={'revision': 0, 'capacity': 13})
    assert updated['capacity'] == 13 and updated['revision'] == 1 and updated['sport_id'] == sport['id']
    api(client, 'PUT', f"/rooms/{room['id']}", user=owner, body={'revision': 1, 'capacity': 0}, expected=422)
    group = api(client, 'POST', '/groups', user=owner, body={'sports_id': sport['id'], 'name': name + ' players'}, expected=201)
    assert group['sports_id'] == sport['id']
    with db() as session:
        persisted = session.get(RoomModel, room['id'])
        assert persisted.sport_id == sport['id'] and persisted.capacity == 13 and persisted.revision == 1
