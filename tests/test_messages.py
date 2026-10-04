from uuid import uuid4
import pytest
from models.message import MessageModel
from models.notification import NotificationModel
from tests.lib import api


@pytest.fixture
def chat(factory):
    owner,member,outsider,pending=[factory.user() for _ in range(4)]
    room=factory.room(owner,visibility='private')
    group=factory.group(owner)
    factory.member(member,room=room)
    factory.member(member,group=group)
    factory.member(pending,room=room,status='pending')
    factory.member(pending,group=group,status='pending')
    factory.friend(owner,member)
    return dict(owner=owner,member=member,outsider=outsider,pending=pending,room=room,group=group)


def target(chat,kind):
    return {'room_id':chat['room']['id']} if kind=='room' else {'group_id':chat['group']['id']} if kind=='group' else {'recipient_id':chat['member']['id']}


@pytest.mark.parametrize('kind',['room','group','direct'])
def test_message_create_canonical_sender_retry_and_persistence(client,db,chat,kind):
    request_id=str(uuid4())
    body={**target(chat,kind),'body':'  Hello friends  ','client_request_id':request_id,'sender_id':chat['outsider']['id'],'type':'system'}
    created=api(client,'POST','/messages',user=chat['owner'],body=body,expected=201)
    assert created['sender_id']==chat['owner']['id'] and created['type']==kind and created['body']=='Hello friends'
    assert created['client_request_id']==request_id
    retry=api(client,'POST','/messages',user=chat['owner'],body={**body,'body':'Changed on retry'},expected=200)
    assert retry==created
    with db() as session:
        rows=session.query(MessageModel).all()
        assert len(rows)==1 and rows[0].body=='Hello friends' and rows[0].sender_id==chat['owner']['id']
        notices=session.query(NotificationModel).all()
        assert len(notices)==1 and notices[0].user_id==chat['member']['id']
    query=target(chat,kind)
    if kind=='direct': query={'user_id':chat['owner']['id']}
    history=api(client,'GET','/messages',user=chat['member'],params=query)
    assert [row['id'] for row in history]==[created['id']]


@pytest.mark.parametrize('kind',['room','group'])
@pytest.mark.parametrize('status',['pending','left','removed','declined'])
def test_unadmitted_members_cannot_read_or_write_private_chats(client,db,factory,kind,status):
    owner,player=factory.user(),factory.user()
    container=factory.room(owner) if kind=='room' else factory.group(owner)
    factory.member(player,**{kind:container},status=status)
    payload={kind+'_id':container['id'],'body':'Denied','client_request_id':str(uuid4())}
    api(client,'POST','/messages',user=player,body=payload,expected=403)
    api(client,'GET','/messages',user=player,params={kind+'_id':container['id']},expected=403)
    assert api(client,'GET','/messages/conversations',user=player,params={'include_empty':True})==[]
    with db() as session: assert session.query(MessageModel).count()==0


def test_cup_roster_is_not_group_chat_membership(client,factory,db):
    owner,player=factory.user(),factory.user()
    group,cup=factory.group(owner),factory.cup(owner)
    factory.member(player,group=group,cup=cup)
    api(client,'POST','/messages',user=player,body={'group_id':group['id'],'body':'Denied','client_request_id':str(uuid4())},expected=403)
    api(client,'GET','/messages',user=player,params={'group_id':group['id']},expected=403)
    with db() as session: assert session.query(MessageModel).count()==0


@pytest.mark.parametrize('case,expected',[('self',400),('missing',404),('stranger',403),('pending',403),('blocked',403),('reverse-blocked',403)])
def test_direct_send_requires_existing_unblocked_accepted_friendship(client,factory,db,case,expected):
    first,second=factory.user(),factory.user()
    if case in ('pending','blocked','reverse-blocked'):
        flags={'user_blocked_other':'true'} if case=='blocked' else {'other_blocked_user':'yes'} if case=='reverse-blocked' else {}
        factory.friend(first,second,status='pending' if case=='pending' else 'accepted',**flags)
    recipient=first['id'] if case=='self' else 999999 if case=='missing' else second['id']
    api(client,'POST','/messages',user=first,body={'recipient_id':recipient,'body':'Denied','client_request_id':str(uuid4())},expected=expected)
    with db() as session: assert session.query(MessageModel).count()==0


def test_block_stops_new_direct_messages_but_preserves_own_history(client,factory,db):
    first,second,third=factory.user(),factory.user(),factory.user()
    factory.friend(first,second)
    sent=api(client,'POST','/messages',user=first,body={'recipient_id':second['id'],'body':'Before block','client_request_id':str(uuid4())},expected=201)
    api(client,'PATCH',f"/friends/{second['id']}",user=first,body={'user_blocked_other':'true'})
    api(client,'POST','/messages',user=second,body={'recipient_id':first['id'],'body':'After block','client_request_id':str(uuid4())},expected=403)
    assert [row['id'] for row in api(client,'GET','/messages',user=second,params={'user_id':first['id']})]==[sent['id']]
    assert api(client,'GET','/messages',user=third,params={'user_id':first['id']})==[]
    with db() as session: assert session.query(MessageModel).count()==1


@pytest.mark.parametrize('bad',[{'body':''},{'body':'   '},{'body':'x'*2001},{'client_request_id':'bad'},{'room_id':99999,'recipient_id':1},{'group_id':1,'recipient_id':1}])
def test_invalid_message_bodies_and_multiple_targets_do_not_persist(client,db,chat,bad):
    payload={'room_id':chat['room']['id'],'body':'Valid','client_request_id':str(uuid4()),**bad}
    api(client,'POST','/messages',user=chat['owner'],body=payload,expected=422)
    with db() as session: assert session.query(MessageModel).count()==0


def test_cross_target_uuid_reuse_rejects_without_duplicate_notifications(client,chat,db):
    request_id=str(uuid4())
    first=api(client,'POST','/messages',user=chat['owner'],body={'room_id':chat['room']['id'],'body':'First','client_request_id':request_id},expected=201)
    api(client,'POST','/messages',user=chat['owner'],body={'group_id':chat['group']['id'],'body':'Second','client_request_id':request_id},expected=409)
    with db() as session:
        assert session.query(MessageModel).count()==1
        assert session.query(NotificationModel).count()==1
        assert session.get(MessageModel,first['id']).type=='room'


def test_history_pagination_is_exact_and_conversations_are_authorized(client,chat,factory):
    rows=[factory.message(chat['owner'],room=chat['room'],body=f'Message {number}') for number in range(7)]
    direct=factory.message(chat['member'],recipient=chat['owner'])
    group=factory.message(chat['owner'],group=chat['group'])
    page=api(client,'GET','/messages',user=chat['member'],params={'room_id':chat['room']['id'],'limit':3})
    assert [row['id'] for row in page]==[value['id'] for value in reversed(rows[-3:])]
    older=api(client,'GET','/messages',user=chat['member'],params={'room_id':chat['room']['id'],'limit':3,'before':page[-1]['id']})
    assert [row['id'] for row in older]==[value['id'] for value in reversed(rows[1:4])]
    conversations=api(client,'GET','/messages/conversations',user=chat['member'])
    assert [row['last_message']['id'] for row in conversations]==[group['id'],direct['id'],rows[-1]['id']]
    assert {row['type'] for row in conversations}=={'room','direct','group'}
    assert api(client,'GET','/messages/conversations',user=chat['outsider'])==[]
    api(client,'GET','/messages',user=chat['member'],expected=422)
    api(client,'GET','/messages',user=chat['member'],params={'room_id':chat['room']['id'],'user_id':chat['owner']['id']},expected=422)
    api(client,'GET','/messages',user=chat['member'],params={'room_id':chat['room']['id'],'limit':101},expected=422)


def test_empty_inbox_targets_allow_first_message_and_include_empty_is_opt_in(client,chat):
    assert api(client,'GET','/messages/conversations',user=chat['member'])==[]
    choices=api(client,'GET','/messages/conversations',user=chat['member'],params={'include_empty':True})
    assert {row['type'] for row in choices}=={'room','group','direct'}
    assert all(row['last_message'] is None for row in choices)
    assert {row['title'] for row in choices}=={chat['room']['title'],chat['group']['name'],chat['owner']['user_name']}


def test_cancelled_room_rejects_new_chat_message_but_keeps_old_history(client,factory,db):
    owner,member=factory.user(),factory.user()
    room=factory.room(owner,status='cancelled')
    factory.member(member,room=room)
    old=factory.message(owner,room=room)
    api(client,'POST','/messages',user=member,body={'room_id':room['id'],'body':'Closed','client_request_id':str(uuid4())},expected=409)
    assert [row['id'] for row in api(client,'GET','/messages',user=member,params={'room_id':room['id']})]==[old['id']]
    with db() as session: assert session.query(MessageModel).count()==1
