import pytest
from models.membership import MembershipModel
from tests.lib import api


def test_friend_request_accept_block_unfriend_are_persisted(client,factory,db):
    requester,target,outsider=factory.user(),factory.user(),factory.user()
    requested=api(client,'POST','/friends',user=requester,body={'other_user_id':target['id']},expected=201)
    assert requested['status']=='pending' and requested['requested'] is True
    assert [row['id'] for row in api(client,'GET','/friends',user=target)]==[requested['id']]
    api(client,'PATCH',f"/friends/{target['id']}",user=requester,body={'status':'accepted'},expected=403)
    accepted=api(client,'PATCH',f"/friends/{requester['id']}",user=target,body={'status':'accepted'})
    assert accepted['accepted'] is True
    api(client,'PATCH',f"/friends/{target['id']}",user=requester,body={'other_blocked_user':'true'},expected=403)
    blocked=api(client,'PATCH',f"/friends/{target['id']}",user=requester,body={'user_blocked_other':'true'})
    assert blocked['user_blocked_other']=='true'
    assert api(client,'GET','/friends',user=outsider)==[]
    api(client,'PATCH',f"/friends/{requester['id']}",user=target,body={'status':'left'})
    with db() as session:
        row=session.get(MembershipModel,requested['id'])
        assert row.status=='left' and row.accepted is False and row.user_blocked_other=='true'


@pytest.mark.parametrize('case,expected',[('self',400),('missing',404),('inverse',409)])
def test_invalid_friend_requests_do_not_create_rows(client,factory,db,case,expected):
    first,second=factory.user(),factory.user()
    target=first['id'] if case=='self' else 99999 if case=='missing' else second['id']
    if case=='inverse': factory.friend(second,first)
    api(client,'POST','/friends',user=first,body={'other_user_id':target},expected=expected)
    with db() as session:
        assert session.query(MembershipModel).count()==(1 if case=='inverse' else 0)


@pytest.mark.parametrize('terminal',['declined','left','removed'])
def test_friendship_terminal_states_cannot_be_reaccepted(client,factory,db,terminal):
    first,second=factory.user(),factory.user()
    row=factory.friend(first,second,status=terminal)
    api(client,'PATCH',f"/friends/{first['id']}",user=second,body={'status':'accepted'},expected=403)
    with db() as session: assert session.get(MembershipModel,row['id']).status==terminal
