from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from models.membership import MembershipModel
from models.room import RoomModel
from tests.lib import api


def race(actions):
    barrier=Barrier(len(actions))
    def execute(action): barrier.wait(timeout=3);return action()
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(execute,actions))


def test_two_stale_room_edits_commit_only_one_revision(client,factory,db):
    owner=factory.user();room=factory.room(owner)
    def edit(title): return lambda: client.put(f"/api/v1/rooms/{room['id']}",headers=owner['headers'],json={'revision':0,'title':title})
    responses=race([edit('First'),edit('Second')])
    assert sorted(response.status_code for response in responses)==[200,409]
    winner=next(response.json()['title'] for response in responses if response.status_code==200)
    with db() as session:
        stored=session.get(RoomModel,room['id']);assert stored.title==winner and stored.revision==1


def test_concurrent_approvals_cannot_overfill_last_available_place(client,factory,db):
    host,first,second=factory.user(),factory.user(),factory.user()
    room=factory.room(host,capacity=2)
    for user in (first,second):factory.member(user,room=room,status='pending',requested=True)
    def accept(user): return lambda: client.patch(f"/api/v1/rooms/{room['id']}/members/{user['id']}",headers=host['headers'],json={'status':'accepted'})
    responses=race([accept(first),accept(second)])
    assert sorted(response.status_code for response in responses)==[200,409]
    with db() as session:
        rows=session.query(MembershipModel).filter_by(room_id=room['id']).all()
        assert sorted(row.status for row in rows)==['accepted','pending']
        assert session.get(RoomModel,room['id']).revision==1


def test_concurrent_slot_selection_has_one_winner_and_no_lost_rows(client,factory,db):
    host,first,second=factory.user(),factory.user(),factory.user()
    room=factory.room(host)
    for user in (first,second):factory.member(user,room=room)
    def select(user): return lambda: client.patch(f"/api/v1/rooms/{room['id']}/members/{user['id']}",headers=user['headers'],json={'position':'1'})
    responses=race([select(first),select(second)])
    assert sorted(response.status_code for response in responses)==[200,409]
    with db() as session:
        rows=session.query(MembershipModel).filter_by(room_id=room['id']).all()
        assert sum(row.position=='1' for row in rows)==1 and len(rows)==2


def test_duplicate_room_requests_and_inverse_friend_requests_create_one_row(client,factory,db):
    host,player=factory.user(),factory.user();room=factory.room(host)
    def request():return client.post(f"/api/v1/rooms/{room['id']}/members",headers=player['headers'],json={})
    responses=race([request,request]);assert sorted(response.status_code for response in responses)==[201,409]
    first,second=factory.user(),factory.user()
    def friend(a,b):return lambda:client.post('/api/v1/friends',headers=a['headers'],json={'other_user_id':b['id']})
    responses=race([friend(first,second),friend(second,first)])
    assert sorted(response.status_code for response in responses)==[201,409]
    with db() as session:
        assert session.query(MembershipModel).filter_by(room_id=room['id']).count()==1
        assert session.query(MembershipModel).filter(MembershipModel.other_user_id.is_not(None)).count()==1
