import json
import time
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from models.message import MessageModel
from models.notification import NotificationModel
from models.user import UserModel
from services import realtime
from tests.lib import api


def user_socket(network,user):
    ticket=api(network.client,'POST','/socket-ticket',user=user,body={})
    assert ticket['expires_in']==30
    socket=connect(network.ws+'/api/v1/ws?ticket='+ticket['ticket'],origin='http://127.0.0.1:5174',open_timeout=2)
    assert json.loads(socket.recv(timeout=2))=={'type':'ready'}
    return socket


def receive(socket,kind):
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:
        event=json.loads(socket.recv(timeout=max(.01,deadline-time.monotonic())))
        if event['type']==kind:
            return event
    raise AssertionError(f'Did not receive {kind}')


def assert_no_message(socket):
    deadline=time.monotonic()+.15
    while time.monotonic()<deadline:
        try:
            event=json.loads(socket.recv(timeout=max(.001,deadline-time.monotonic())))
        except TimeoutError:
            return
        assert event['type']!='message.created',event


@pytest.mark.parametrize('kind',['room','group','direct'])
def test_rest_message_is_committed_and_delivered_only_to_current_eligible_users(network,factory,db,kind):
    owner,member,outsider,pending=[factory.user() for _ in range(4)]
    if kind=='direct':
        factory.friend(owner,member)
        body={'recipient_id':member['id']}
    else:
        container=factory.room(owner,visibility='private') if kind=='room' else factory.group(owner)
        factory.member(member,**{kind:container})
        factory.member(pending,**{kind:container},status='pending')
        body={kind+'_id':container['id']}
    with user_socket(network,owner) as own, user_socket(network,member) as admitted, user_socket(network,outsider) as outside, user_socket(network,pending) as waiting:
        request={**body,'body':'Live persisted message','client_request_id':str(uuid4())}
        created=api(network.client,'POST','/messages',user=owner,body=request,expected=201)
        assert receive(own,'message.created')['message']==created
        assert receive(admitted,'message.created')['message']==created
        notification=receive(admitted,'notification.created')['notification']
        assert notification['target']['type']==kind and notification['text']
        assert_no_message(outside);assert_no_message(waiting)
        api(network.client,'POST','/messages',user=owner,body=request,expected=200)
        assert_no_message(own);assert_no_message(admitted)
        with db() as session:
            assert session.get(MessageModel,created['id']).body=='Live persisted message'
            assert session.query(NotificationModel).count()==1


@pytest.mark.parametrize('kind',['room','group'])
def test_existing_socket_loses_chat_access_immediately_after_removal(network,factory,db,kind):
    owner,member=factory.user(),factory.user()
    container=factory.room(owner) if kind=='room' else factory.group(owner)
    factory.member(member,**{kind:container})
    with user_socket(network,member) as socket:
        api(network.client,'PATCH',f"/{kind}s/{container['id']}/members/{member['id']}",user=owner,body={'status':'removed'})
        api(network.client,'POST','/messages',user=owner,body={kind+'_id':container['id'],'body':'After removal','client_request_id':str(uuid4())},expected=201)
        assert_no_message(socket)
        api(network.client,'GET','/messages',user=member,params={kind+'_id':container['id']},expected=403)
        api(network.client,'PATCH',f"/{kind}s/{container['id']}/members/{member['id']}",user=member,body={'status':'accepted'},expected=403)


def test_mark_read_events_reach_own_devices_and_logout_closes_all_old_tokens(network,factory,db):
    owner,member=factory.user(),factory.user()
    group=factory.group(owner)
    with user_socket(network,member) as first, user_socket(network,member) as second:
        api(network.client,'POST',f"/groups/{group['id']}/members",user=owner,body={'user_id':member['id']},expected=201)
        first_notice=receive(first,'notification.created')['notification']
        assert receive(second,'notification.created')['notification']['id']==first_notice['id']
        api(network.client,'PATCH',f"/notifications/{first_notice['id']}",user=member,body={'read':True})
        assert receive(first,'notifications.updated')=={'type':'notifications.updated'}
        assert receive(second,'notifications.updated')=={'type':'notifications.updated'}
        api(network.client,'POST','/auth/logout',user=member,expected=204)
        for socket in (first,second):
            with pytest.raises(ConnectionClosed) as closed:
                socket.recv(timeout=2)
            assert closed.value.rcvd.code==1008
    with db() as session: assert session.get(UserModel,member['id']).token_version==1
    assert realtime.realtime_hub.connections=={}


def test_ticket_is_single_use_bad_origins_fail_and_protocol_is_bounded(network,factory,monkeypatch):
    user=factory.user()
    ticket=api(network.client,'POST','/socket-ticket',user=user,body={})['ticket']
    url=network.ws+'/api/v1/ws?ticket='+ticket
    with connect(url,origin='http://127.0.0.1:5174') as socket:
        assert json.loads(socket.recv(timeout=2))=={'type':'ready'}
        with pytest.raises(InvalidStatus) as duplicate:
            connect(url)
        assert duplicate.value.response.status_code==403
        socket.send(json.dumps({'action':'ping'}));assert json.loads(socket.recv(timeout=2))=={'type':'pong'}
        socket.send(json.dumps({'action':'send','sender_id':999,'body':'Unauthorized'}))
        assert json.loads(socket.recv(timeout=2))['type']=='error'
        socket.send(b'x'*(realtime.MAX_MESSAGE_BYTES+1))
        with pytest.raises(ConnectionClosed) as oversized:
            socket.recv(timeout=2)
        assert oversized.value.rcvd.code==1009
    fresh=api(network.client,'POST','/socket-ticket',user=user,body={})['ticket']
    with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws?ticket='+fresh,origin='http://evil.example')
    assert realtime.realtime_hub.connections=={}


def test_ticket_expiry_and_revocation_before_connect_are_rejected(network,factory,db,monkeypatch):
    user=factory.user()
    expired=api(network.client,'POST','/socket-ticket',user=user,body={})['ticket']
    token,_,owner=realtime.tickets.values[expired]
    realtime.tickets.values[expired]=(token,0,owner)
    with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws?ticket='+expired)
    revoked=api(network.client,'POST','/socket-ticket',user=user,body={})['ticket']
    api(network.client,'POST','/auth/logout',user=user,expected=204)
    with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws?ticket='+revoked)
    assert realtime.realtime_hub.connections=={} and realtime.realtime_hub.by_ip=={}


def test_connection_limit_recovers_when_a_socket_leaves(network,factory,monkeypatch):
    user=factory.user()
    monkeypatch.setattr(realtime,'MAX_CONNECTIONS_PER_IP',1)
    with user_socket(network,user) as first:
        ticket=api(network.client,'POST','/socket-ticket',user=user,body={})['ticket']
        with pytest.raises(InvalidStatus): connect(network.ws+'/api/v1/ws?ticket='+ticket)
        first.send(json.dumps({'action':'ping'}));assert receive(first,'pong')=={'type':'pong'}
    deadline=time.monotonic()+2
    while realtime.realtime_hub.by_ip and time.monotonic()<deadline: time.sleep(.01)
    with user_socket(network,user) as fresh:
        fresh.send(json.dumps({'action':'ping'}));assert receive(fresh,'pong')=={'type':'pong'}


def test_concurrent_same_uuid_commits_one_message_and_one_notice(network,factory,db):
    first,second=factory.user(),factory.user()
    factory.friend(first,second)
    payload={'recipient_id':second['id'],'body':'One logical send','client_request_id':str(uuid4())}
    def send(_): return network.client.post('/api/v1/messages',headers=first['headers'],json=payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(send,range(2)))
    assert sorted(response.status_code for response in responses)==[200,201]
    assert responses[0].json()['id']==responses[1].json()['id']
    with db() as session:
        assert session.query(MessageModel).count()==1 and session.query(NotificationModel).count()==1


def test_concurrent_cross_target_uuid_reuse_is_conflict_not_server_error(network,factory,db):
    owner=factory.user()
    groups=[factory.group(owner) for _ in range(2)]
    request_id=str(uuid4())
    def send(group): return network.client.post('/api/v1/messages',headers=owner['headers'],json={'group_id':group['id'],'body':'Cross-target','client_request_id':request_id})
    with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(send,groups))
    assert sorted(response.status_code for response in responses)==[201,409]
    with db() as session: assert session.query(MessageModel).count()==1
