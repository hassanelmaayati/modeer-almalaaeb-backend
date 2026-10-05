import json
import time
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
import pytest
from controllers import lobby_ws
from tests.lib import api,room_body
from tests.test_realtime import receive


def lobby(network,district=None):
    socket=connect(network.ws+'/api/v1/ws/lobby',origin='http://127.0.0.1:5174')
    socket.send(json.dumps({'action':'subscribe','district':district}))
    assert json.loads(socket.recv(timeout=2))=={'type':'subscribed','district':district}
    return socket


def test_public_rest_create_update_move_cancel_delivers_exact_safe_events(network,factory):
    owner,sport=factory.user(),factory.sport()
    with lobby(network,'capital') as capital,lobby(network,'southern') as southern,lobby(network) as all_districts:
        room=api(network.client,'POST','/rooms',user=owner,body=room_body(sport['id']),expected=201)
        event=receive(capital,'room_created')
        assert event['room']['id']==room['id'] and event['room']['slots_left']==3
        assert set(event['room'])=={'id','title','sport_id','sport_name','district','area','starts_at','capacity','slots_left','difficulty','revision'}
        assert receive(all_districts,'room_created')==event
        with pytest.raises(TimeoutError): southern.recv(timeout=.1)
        moved=api(network.client,'PUT',f"/rooms/{room['id']}",user=owner,body={'revision':0,'title':'Moved','district':'southern','area':'Riffa'})
        removed=receive(capital,'room_removed')
        assert removed['room_id']==room['id'] and removed['reason']=='moved'
        assert receive(southern,'room_created')['room']['title']=='Moved'
        api(network.client,'POST',f"/rooms/{room['id']}/cancel",user=owner,body={'reason':'Rain'})
        removal=receive(southern,'room_removed')
        assert removal['reason']=='cancelled' and removal['room_id']==room['id']


def test_lobby_membership_changes_fill_remove_and_leave_republish_with_versions(network,factory):
    host,player=factory.user(),factory.user()
    sport=factory.sport()
    with lobby(network) as socket:
        room=api(network.client,'POST','/rooms',user=host,body=room_body(sport['id'],capacity=2),expected=201)
        initial=receive(socket,'room_created')['room']
        api(network.client,'POST',f"/rooms/{room['id']}/members",user=player,body={},expected=201)
        with pytest.raises(TimeoutError): socket.recv(timeout=.1)
        api(network.client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=host,body={'status':'accepted'})
        assert receive(socket,'room_removed')['reason']=='full'
        api(network.client,'DELETE',f"/rooms/{room['id']}/members/me",user=player,expected=204)
        reopened=receive(socket,'room_created')['room']
        assert reopened['slots_left']==1 and reopened['revision']>initial['revision']


def test_private_changes_are_silent_and_district_switch_unsubscribe_cleanup_work(network,factory):
    host,sport=factory.user(),factory.sport()
    with lobby(network,'capital') as socket:
        api(network.client,'POST','/rooms',user=host,body=room_body(sport['id'],visibility='private'),expected=201)
        with pytest.raises(TimeoutError): socket.recv(timeout=.1)
        socket.send(json.dumps({'action':'subscribe','district':'southern'}));assert receive(socket,'subscribed')['district']=='southern'
        api(network.client,'POST','/rooms',user=host,body=room_body(sport['id'],district='capital'),expected=201)
        with pytest.raises(TimeoutError): socket.recv(timeout=.1)
        socket.send(json.dumps({'action':'unsubscribe'}));assert receive(socket,'unsubscribed')=={'type':'unsubscribed'}
        api(network.client,'POST','/rooms',user=host,body=room_body(sport['id'],district='southern',area='Riffa'),expected=201)
        with pytest.raises(TimeoutError): socket.recv(timeout=.1)
    deadline=time.monotonic()+2
    while lobby_ws.open_total and time.monotonic()<deadline: time.sleep(.01)
    assert lobby_ws.open_total==0 and lobby_ws.open_by_ip=={} and lobby_ws.lobby_hub.connection_count()==0


@pytest.mark.parametrize('district',['mars',5,['capital']])
def test_invalid_lobby_district_stays_connected(network,district):
    with connect(network.ws+'/api/v1/ws/lobby') as socket:
        socket.send(json.dumps({'action':'subscribe','district':district}))
        assert receive(socket,'error')['detail']
        socket.send(json.dumps({'action':'ping'}));assert receive(socket,'pong')=={'type':'pong'}


def test_lobby_origin_caps_binary_and_malformed_frames_are_enforced(network,monkeypatch):
    with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws/lobby',origin='http://evil.example')
    monkeypatch.setattr(lobby_ws,'MAX_CONNECTIONS',1)
    with lobby(network) as socket:
        with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws/lobby')
        socket.send('bad-json');socket.send(json.dumps({'action':'unexpected'}))
        socket.send(json.dumps({'action':'ping'}));assert receive(socket,'pong')=={'type':'pong'}
        socket.send(b'x'*(lobby_ws.MAX_MESSAGE_BYTES+1))
        with pytest.raises(ConnectionClosed) as closed: socket.recv(timeout=2)
        assert closed.value.rcvd.code==1009
