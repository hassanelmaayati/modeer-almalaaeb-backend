import pytest
from tests.lib import api, future


def test_joined_rooms_lists_only_accepted_rooms_the_user_does_not_host(client,factory):
    host,player,other=factory.user(),factory.user(),factory.user()
    sport=factory.sport()
    later=factory.room(host,sport,starts_at=future(30),ends_at=future(31))
    sooner=factory.room(host,sport,starts_at=future(5),ends_at=future(6))
    pending=factory.room(host,sport)
    declined=factory.room(host,sport)
    factory.member(player,room=later)
    factory.member(player,room=sooner)
    factory.member(player,room=pending,status='pending',requested=True)
    factory.member(player,room=declined,status='declined')
    factory.member(other,room=pending)
    own=factory.room(player,sport)
    api(client,'GET','/rooms/joined',expected=401)
    rooms=api(client,'GET','/rooms/joined',user=player)
    assert [row['id'] for row in rooms['items']]==[sooner['id'],later['id']]
    assert (rooms['total'],rooms['has_more'])==(2,False)
    assert own['id'] not in [row['id'] for row in rooms['items']]
    assert [row['id'] for row in api(client,'GET','/rooms/joined',user=host)['items']]==[]
    assert [row['id'] for row in api(client,'GET','/rooms/joined',user=other)['items']]==[pending['id']]


def test_joined_rooms_use_the_shared_filters_ordering_and_paging(client,factory):
    host,player=factory.user(),factory.user()
    football,swimming=factory.sport('Football'),factory.sport('Swimming')
    first=factory.room(host,swimming,starts_at=future(5),ends_at=future(6),difficulty='beginners')
    second=factory.room(host,football,starts_at=future(30),ends_at=future(31),difficulty='advanced')
    third=factory.room(host,swimming,status='completed',starts_at=future(50),ends_at=future(51))
    for room in (first,second,third):
        factory.member(player,room=room)
    def ids(**params): return [row['id'] for row in api(client,'GET','/rooms/joined',user=player,params=params)['items']]
    assert ids()==[first['id'],second['id'],third['id']]
    assert ids(status='completed')==[third['id']]
    assert ids(sport_id=swimming['id'])==[first['id'],third['id']]
    assert ids(difficulty='advanced')==[second['id']]
    assert ids(order='desc')==[third['id'],second['id'],first['id']]
    assert ids(starts_from=future(20).isoformat(),starts_to=future(40).isoformat())==[second['id']]
    page=api(client,'GET','/rooms/joined',user=player,params={'limit':2})
    assert ([row['id'] for row in page['items']],page['total'],page['has_more'])==([first['id'],second['id']],3,True)
    assert ids(limit=2,offset=2)==[third['id']]


def test_joined_rooms_show_the_public_view_only(client,factory):
    host,player=factory.user(),factory.user()
    room=factory.room(host)
    factory.member(player,room=room)
    row=api(client,'GET','/rooms/joined',user=player)['items'][0]
    assert 'venue_notes' not in row and 'venue_location' not in row


@pytest.mark.parametrize('params',[
    {'status':'archived'},{'visibility':'hidden'},{'difficulty':'expert'},{'order':'sideways'},
    {'limit':0},{'limit':101},{'offset':-1},
])
def test_joined_rooms_rejects_invalid_filters(client,factory,params):
    api(client,'GET','/rooms/joined',user=factory.user(),params=params,expected=422)
