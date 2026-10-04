import pytest
from models.group import GroupModel
from models.membership import MembershipModel
from tests.lib import api


def test_group_create_read_update_and_owner_permissions_are_persisted(client,factory,db):
    owner,other=factory.user(),factory.user()
    sport=factory.sport()
    group=api(client,'POST','/groups',user=owner,body={'name':'Evening team','sports_id':sport['id'],'description':'Meet weekly'},expected=201)
    assert group['owner_id']==owner['id'] and group['sports_id']==sport['id']
    assert [value['id'] for value in api(client,'GET','/groups')]==[group['id']]
    assert api(client,'GET',f"/groups/{group['id']}")['name']=='Evening team'
    api(client,'PUT',f"/groups/{group['id']}",user=other,body={'name':'Denied'},expected=403)
    edited=api(client,'PUT',f"/groups/{group['id']}",user=owner,body={'name':'Updated team','description':'Friday'})
    assert edited['name']=='Updated team'
    with db() as session:
        stored=session.get(GroupModel,group['id'])
        assert (stored.name,stored.description,stored.owner_id)==('Updated team','Friday',owner['id'])
    api(client,'GET','/groups/99999',expected=404)


def test_group_invitation_accept_leave_has_isolated_membership_and_notifications(client,factory,db):
    owner,member,outsider=factory.user(),factory.user(),factory.user()
    group=factory.group(owner)
    api(client,'POST',f"/groups/{group['id']}/members",user=outsider,body={'user_id':member['id']},expected=403)
    invited=api(client,'POST',f"/groups/{group['id']}/members",user=owner,body={'user_id':member['id']},expected=201)
    assert (invited['status'],invited['requested'],invited['accepted'])==('pending',False,False)
    api(client,'POST',f"/groups/{group['id']}/members",user=owner,body={'user_id':member['id']},expected=409)
    accepted=api(client,'PATCH',f"/groups/{group['id']}/members/{member['id']}",user=member,body={'status':'accepted'})
    assert accepted['accepted'] is True
    left=api(client,'PATCH',f"/groups/{group['id']}/members/{member['id']}",user=member,body={'status':'left'})
    assert left['status']=='left' and left['accepted'] is False
    with db() as session:
        rows=session.query(MembershipModel).filter_by(group_id=group['id'],cup_id=None).all()
        assert len(rows)==1 and rows[0].status=='left'
    notices=api(client,'GET','/notifications',user=member)
    assert any(item['target']=={'type':'group','id':group['id']} for item in notices['items'])


@pytest.mark.parametrize('terminal',['left','declined','removed'])
def test_terminal_group_members_cannot_restore_themselves(client,factory,db,terminal):
    owner,member=factory.user(),factory.user()
    group=factory.group(owner)
    row=factory.member(member,group=group,status=terminal)
    api(client,'PATCH',f"/groups/{group['id']}/members/{member['id']}",user=member,body={'status':'accepted'},expected=403)
    with db() as session:
        assert session.get(MembershipModel,row['id']).status==terminal


def test_owner_removal_cannot_be_spoofed_and_roster_projection_is_exact(client,factory,db):
    owner,accepted,pending,outsider=[factory.user() for _ in range(4)]
    group=factory.group(owner)
    accepted_row=factory.member(accepted,group=group)
    factory.member(pending,group=group,status='pending')
    # Cup roster rows sharing group_id remain separate from ordinary membership.
    cup=factory.cup(owner)
    factory.member(outsider,group=group,cup=cup)
    owner_ids={row['user_id'] for row in api(client,'GET',f"/groups/{group['id']}/members",user=owner)}
    assert owner_ids=={accepted['id'],pending['id']}
    assert {row['user_id'] for row in api(client,'GET',f"/groups/{group['id']}/members",user=pending)}=={accepted['id'],pending['id']}
    api(client,'PATCH',f"/groups/{group['id']}/members/{accepted['id']}",user=outsider,body={'status':'removed'},expected=403)
    removed=api(client,'PATCH',f"/groups/{group['id']}/members/{accepted['id']}",user=owner,body={'status':'removed'})
    assert removed['accepted'] is False
    with db() as session:
        assert session.get(MembershipModel,accepted_row['id']).status=='removed'


@pytest.mark.parametrize('body,expected', [({},422), ({'status':'bogus'},403)])
def test_invalid_group_status_does_not_change_membership(client,factory,db,body,expected):
    owner,member=factory.user(),factory.user()
    group=factory.group(owner)
    row=factory.member(member,group=group,status='pending')
    response=client.patch(f"/api/v1/groups/{group['id']}/members/{member['id']}",headers=member['headers'],json=body)
    assert response.status_code == expected,response.text
    with db() as session: assert session.get(MembershipModel,row['id']).status=='pending'
