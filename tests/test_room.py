from datetime import timedelta
import pytest
from models.room import RoomModel
from models.membership import MembershipModel
from models.message import MessageModel
from tests.lib import api, future, room_body


def test_discovery_filters_have_exact_results_and_private_projection(client,factory):
    host=factory.user()
    first,second=factory.sport(),factory.sport('Running')
    capital=factory.room(host,first,district='capital',difficulty='medium')
    southern=factory.room(host,second,district='southern',starts_at=future(30),ends_at=future(31))
    factory.room(host,first,visibility='private')
    factory.room(host,first,status='cancelled')
    factory.room(host,first,starts_at=future(0.1),ends_at=future(1))
    assert [row['id'] for row in api(client,'GET','/rooms')]==[capital['id'],southern['id']]
    queries=[({'sport_id':first['id']},[capital['id']]),({'difficulty':'medium'},[capital['id']]),({'district':'southern'},[southern['id']]),
             ({'district':'capital','sport_id':second['id']},[]),({'starts_from':future(27).isoformat()},[southern['id']]),
             ({'starts_to':future(27).isoformat()},[capital['id']])]
    for query,ids in queries:
        rows=api(client,'GET','/rooms',params=query)
        assert [row['id'] for row in rows]==ids
        assert all('venue_notes' not in row for row in rows)
    api(client,'GET','/rooms',params={'district':'mars'},expected=422)


def test_detail_and_roster_require_actual_admission(client,factory):
    host,accepted,pending,outsider=[factory.user() for _ in range(4)]
    room=factory.room(host,visibility='private')
    accepted_row=factory.member(accepted,room=room)
    pending_row=factory.member(pending,room=room,status='pending',requested=False)
    for user in [host,accepted]:
        assert api(client,'GET',f"/rooms/{room['id']}",user=user)['venue_notes']=='Private Court 7'
    assert 'venue_notes' not in api(client,'GET',f"/rooms/{room['id']}",user=pending)
    api(client,'GET',f"/rooms/{room['id']}",user=outsider,expected=404)
    api(client,'GET',f"/rooms/{room['id']}",expected=404)
    assert {row['id'] for row in api(client,'GET',f"/rooms/{room['id']}/members",user=host)}=={accepted_row['id'],pending_row['id']}
    assert [row['id'] for row in api(client,'GET',f"/rooms/{room['id']}/members",user=accepted)]==[accepted_row['id']]
    assert [row['id'] for row in api(client,'GET',f"/rooms/{room['id']}/members",user=pending)]==[pending_row['id']]
    public=factory.room(host)
    assert api(client,'GET',f"/rooms/{public['id']}/members")==[]
    api(client,'GET','/rooms/999999',expected=404)


def test_create_edit_ignore_server_fields_and_preserve_canonical_values(client,factory,db):
    host,outsider=factory.user(),factory.user()
    sport=factory.sport()
    created=api(client,'POST','/rooms',user=host,body=room_body(sport['id'],host_id=outsider['id'],status='cancelled',revision=100,host_generation=100),expected=201)
    assert (created['host_id'],created['status'],created['revision'],created['host_generation'])==(host['id'],'open',0,0)
    api(client,'PUT',f"/rooms/{created['id']}",user=outsider,body={'revision':0,'title':'Denied'},expected=403)
    updated=api(client,'PUT',f"/rooms/{created['id']}",user=host,body={'revision':0,'title':'Changed','district':'northern','area':'Budaiya','description':'New'})
    assert (updated['title'],updated['district'],updated['revision'])==('Changed','northern',1)
    api(client,'PUT',f"/rooms/{created['id']}",user=host,body={'revision':0,'title':'Stale'},expected=409)
    with db() as session:
        row=session.get(RoomModel,created['id'])
        assert (row.title,row.district,row.revision)==('Changed','northern',1)


@pytest.mark.parametrize('change', [
    {'capacity':0},{'difficulty':'expert'},{'district':'mars'},{'visibility':'hidden'},{'admission_policy':'auto'},
    {'visibility':'group'},{'starts_at':future(0.5).isoformat()},{'starts_at':future(24*15).isoformat()},
    {'starts_at':'2026-10-10T18:00:00'},{'ends_at':future(1).isoformat()},{'title':''},{'distance_km':-1},
])
def test_invalid_room_creation_leaves_database_empty(client,factory,db,change):
    host,sport=factory.user(),factory.sport()
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],**change),expected=422)
    with db() as session: assert session.query(RoomModel).count()==0


@pytest.mark.parametrize('field',['sport_id','title','difficulty','starts_at','ends_at','capacity','slot_layout','visibility','admission_policy','district','area'])
def test_required_update_fields_cannot_be_null(client,factory,db,field):
    host=factory.user()
    room=factory.room(host)
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,field:None},expected=422)
    with db() as session: assert session.get(RoomModel,room['id']).revision==0


def test_group_room_ownership_and_unknown_entities(client,factory,db):
    host,outsider=factory.user(),factory.user()
    sport=factory.sport()
    own=factory.group(host,sport)
    foreign=factory.group(outsider,sport)
    created=api(client,'POST','/rooms',user=host,body=room_body(sport['id'],visibility='group',group_id=own['id']),expected=201)
    assert created['group_id']==own['id']
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],group_id=foreign['id']),expected=403)
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],group_id=99999),expected=404)
    api(client,'POST','/rooms',user=host,body=room_body(99999),expected=404)
    with db() as session: assert session.query(RoomModel).count()==1


def test_capacity_format_change_revalidates_and_declining_capacity_never_overbooks(client,factory,db):
    host,member=factory.user(),factory.user()
    swimming=factory.sport()
    football=factory.sport('Football',formats=[{'key':'5v5','capacity':10}])
    api(client,'POST','/rooms',user=host,body=room_body(football['id'],capacity=7),expected=422)
    room=factory.room(host,swimming,capacity=4)
    factory.member(member,room=room)
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,'sport_id':football['id']},expected=422)
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,'capacity':1},expected=409)
    with db() as session:
        row=session.get(RoomModel,room['id'])
        assert (row.capacity,row.sport_id,row.revision)==(4,swimming['id'],0)


def test_cutoff_freezes_schedule_but_allows_description_and_admission_stays_closed(client,factory,db):
    host,member=factory.user(),factory.user()
    room=factory.room(host,starts_at=future(0.1),ends_at=future(1))
    assert api(client,'GET','/rooms')==[]
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,'venue_notes':'Changed'},expected=409)
    edited=api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,'description':'Weather note'})
    assert edited['description']=='Weather note'
    api(client,'POST',f"/rooms/{room['id']}/members",user=member,body={},expected=409)
    with db() as session: assert session.query(MembershipModel).count()==0


def test_cancel_is_atomic_with_system_message_and_private_history(client,factory,db):
    host,member,outsider=[factory.user() for _ in range(3)]
    room=factory.room(host)
    factory.member(member,room=room)
    api(client,'POST',f"/rooms/{room['id']}/cancel",user=outsider,body={'reason':'Denied'},expected=403)
    api(client,'POST',f"/rooms/{room['id']}/cancel",user=host,body={},expected=422)
    cancelled=api(client,'POST',f"/rooms/{room['id']}/cancel",user=host,body={'reason':' Rain '})
    assert cancelled['status']=='cancelled' and cancelled['revision']==1
    messages=api(client,'GET','/messages',user=member,params={'room_id':room['id']})
    assert len(messages)==1 and messages[0]['body']=='Room cancelled: Rain' and messages[0]['sender_id'] is None
    api(client,'GET','/messages',user=outsider,params={'room_id':room['id']},expected=403)
    api(client,'POST',f"/rooms/{room['id']}/cancel",user=host,body={'reason':'Again'},expected=409)
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':1,'title':'Closed'},expected=409)
    with db() as session:
        assert session.get(RoomModel,room['id']).status=='cancelled'
        assert session.query(MessageModel).filter_by(room_id=room['id']).count()==1


def test_request_approve_position_attendance_rating_leave_are_persisted(client,factory,db):
    host,player,outsider=[factory.user() for _ in range(3)]
    room=factory.room(host)
    requested=api(client,'POST',f"/rooms/{room['id']}/members",user=player,body={},expected=201)
    assert requested['status']=='pending' and requested['requested'] is True and requested['accepted'] is False
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=player,body={'status':'accepted'},expected=403)
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=outsider,body={'status':'accepted'},expected=403)
    accepted=api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=host,body={'status':'accepted'})
    assert accepted['accepted'] is True
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=player,body={'position':'lane-1'})
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=player,body={'attendance':'present'},expected=403)
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=host,body={'rating':4},expected=409)
    rated=api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=host,body={'attendance':'present','rating':4})
    assert rated['rating']==4
    before=api(client,'GET',f"/rooms/{room['id']}")
    api(client,'DELETE',f"/rooms/{room['id']}/members/me",user=player,expected=204)
    api(client,'DELETE',f"/rooms/{room['id']}/members/me",user=player,expected=204)
    after=api(client,'GET',f"/rooms/{room['id']}")
    assert after['revision']==before['revision']+1 and after['slots_left']==3
    with db() as session:
        row=session.get(MembershipModel,requested['id'])
        assert row.status=='left' and row.accepted is False and row.position is None and row.rating==4


@pytest.mark.parametrize('status',['left','removed','declined'])
def test_terminal_room_members_cannot_rejoin_or_be_approved(client,factory,db,status):
    host,player=factory.user(),factory.user()
    room=factory.room(host)
    row=factory.member(player,room=room,status=status)
    api(client,'POST',f"/rooms/{room['id']}/members",user=player,body={},expected=409)
    api(client,'PATCH',f"/rooms/{room['id']}/members/{player['id']}",user=host,body={'status':'accepted'},expected=403)
    with db() as session: assert session.get(MembershipModel,row['id']).status==status


def test_host_invitation_acceptance_capacity_and_slot_collision(client,factory,db):
    host,first,second=[factory.user() for _ in range(3)]
    room=factory.room(host,capacity=2)
    api(client,'POST',f"/rooms/{room['id']}/members",user=host,body={'user_id':host['id']},expected=409)
    invited=api(client,'POST',f"/rooms/{room['id']}/members",user=host,body={'user_id':first['id']},expected=201)
    assert invited['requested'] is False
    second_row=factory.member(second,room=room,status='pending',requested=True)
    api(client,'PATCH',f"/rooms/{room['id']}/members/{first['id']}",user=first,body={'status':'accepted','position':'slot-a'})
    api(client,'PATCH',f"/rooms/{room['id']}/members/{second['id']}",user=host,body={'status':'accepted'},expected=409)
    listing=api(client,'GET','/rooms')
    assert len(listing)==1 and listing[0]['id']==room['id'] and listing[0]['slots_left']==0
    with db() as session: assert session.get(MembershipModel,second_row['id']).status=='pending'
    roomy=factory.room(host,capacity=4)
    a=factory.member(first,room=roomy,position='slot-a')
    b=factory.member(second,room=roomy)
    api(client,'PATCH',f"/rooms/{roomy['id']}/members/{second['id']}",user=second,body={'position':'slot-a'},expected=409)
    with db() as session: assert session.get(MembershipModel,b['id']).position is None


@pytest.mark.parametrize('field',['title','area'])
def test_whitespace_only_room_fields_are_rejected_without_persisting(client,factory,db,field):
    host,sport=factory.user(),factory.sport()
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],**{field:'   '}),expected=422)
    room=factory.room(host,sport)
    api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,field:'  '},expected=422)
    with db() as session:
        row=session.get(RoomModel,room['id'])
        assert row.revision==0 and row.status=='open'
        assert session.query(RoomModel).count()==1
        assert session.query(MessageModel).count()==0
        from models.notification import NotificationModel
        assert session.query(NotificationModel).count()==0


def test_whitespace_cancel_reason_changes_neither_room_nor_notices(client,factory,db):
    host=factory.user();room=factory.room(host)
    api(client,'POST',f"/rooms/{room['id']}/cancel",user=host,body={'reason':'   '},expected=422)
    with db() as session:
        row=session.get(RoomModel,room['id'])
        assert row.status=='open' and row.revision==0
        assert session.query(MessageModel).count()==0
        from models.notification import NotificationModel
        assert session.query(NotificationModel).count()==0


PIN={'latitude':26.2285,'longitude':50.5860}


def test_area_must_belong_to_district_on_create_and_update(client,factory):
    host,sport=factory.user(),factory.sport()
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],district='capital',area='Riffa'),expected=422)
    room=factory.room(host,sport)  # capital / Manama
    path=f"/rooms/{room['id']}"
    # A new district alone, or a new area alone, must still match the stored value
    api(client,'PUT',path,user=host,body={'revision':0,'district':'southern'},expected=422)
    api(client,'PUT',path,user=host,body={'revision':0,'area':'Riffa'},expected=422)
    updated=api(client,'PUT',path,user=host,body={'revision':0,'district':'southern','area':'Riffa'})
    assert (updated['district'],updated['area'])==('southern','Riffa')


def test_venue_location_is_private_and_round_trips(client,factory,db):
    host,outsider,sport=factory.user(),factory.user(),factory.sport()
    created=api(client,'POST','/rooms',user=host,body=room_body(sport['id'],venue_location=PIN),expected=201)
    assert created['venue_location']==PIN
    with db() as session:
        assert session.get(RoomModel,created['id']).venue_location==PIN
    assert api(client,'GET',f"/rooms/{created['id']}",user=host)['venue_location']==PIN
    for viewer in [None,outsider]:
        row=api(client,'GET',f"/rooms/{created['id']}",user=viewer)
        assert 'venue_location' not in row and 'venue_notes' not in row
    assert all('venue_location' not in row for row in api(client,'GET','/rooms'))


@pytest.mark.parametrize('location',[
    {'latitude':51.5,'longitude':-0.12},{'latitude':95,'longitude':50.5},{'latitude':26.2},
])
def test_invalid_venue_location_is_rejected(client,factory,location):
    host,sport=factory.user(),factory.sport()
    api(client,'POST','/rooms',user=host,body=room_body(sport['id'],venue_location=location),expected=422)


def test_venue_location_can_be_updated_until_the_cutoff(client,factory):
    host=factory.user()
    room=factory.room(host)
    updated=api(client,'PUT',f"/rooms/{room['id']}",user=host,body={'revision':0,'venue_location':PIN})
    assert updated['venue_location']==PIN
    soon=factory.room(host,starts_at=future(0.1),ends_at=future(1))
    api(client,'PUT',f"/rooms/{soon['id']}",user=host,body={'revision':0,'venue_location':PIN},expected=409)
