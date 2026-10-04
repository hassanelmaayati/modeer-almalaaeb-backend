import pytest
from sqlalchemy.exc import IntegrityError
from models.membership import MembershipModel
from models.message import MessageModel
from models.room import RoomModel


@pytest.mark.parametrize('kind',['room','group','cup','friend','position'])
def test_database_rejects_duplicate_memberships_under_actual_postgres_constraints(factory,db,kind):
    owner,first,second=factory.user(),factory.user(),factory.user()
    room,group,cup=factory.room(owner),factory.group(owner),factory.cup(owner)
    if kind=='friend':
        existing=factory.friend(first,second)
        conflicting=dict(user_id=second['id'],other_user_id=first['id'],status='pending')
    elif kind=='position':
        existing=factory.member(first,room=room,position='slot-a')
        conflicting=dict(user_id=second['id'],room_id=room['id'],position='slot-a',status='accepted')
    else:
        args={kind:{'room':room,'group':group,'cup':cup}[kind]}
        if kind=='cup': args['group']=group
        existing=factory.member(first,**args)
        conflicting={key:value for key,value in existing.items() if key not in ('id','created_at','updated_at')}
    with db() as session:
        session.add(MembershipModel(**conflicting))
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()
    with db() as session: assert session.query(MembershipModel).count()==1


def test_ordinary_group_and_cup_roster_are_distinct_valid_memberships(factory,db):
    owner,player=factory.user(),factory.user()
    group,cup=factory.group(owner),factory.cup(owner)
    ordinary=factory.member(player,group=group)
    roster=factory.member(player,group=group,cup=cup)
    with db() as session:
        assert session.query(MembershipModel).count()==2
        assert session.get(MembershipModel,ordinary['id']).cup_id is None
        assert session.get(MembershipModel,roster['id']).cup_id==cup['id']


@pytest.mark.parametrize('problem',['foreign-key','two-targets','empty-body','wrong-type','self'])
def test_message_constraints_reject_invalid_rows_without_side_effects(factory,db,problem):
    owner,recipient=factory.user(),factory.user()
    room,group=factory.room(owner),factory.group(owner)
    values=dict(sender_id=owner['id'],group_id=group['id'],type='group',body='Valid')
    if problem=='foreign-key': values['group_id']=99999
    if problem=='two-targets': values['room_id']=room['id']
    if problem=='empty-body': values['body']='   '
    if problem=='wrong-type': values['type']='direct'
    if problem=='self': values.update(group_id=None,type='direct',recipient_id=owner['id'])
    with db() as session:
        session.add(MessageModel(**values))
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()
    with db() as session: assert session.query(MessageModel).count()==0


def test_room_database_checks_are_enforced_without_api_validation(factory,db):
    owner=factory.user();room=factory.room(owner)
    with db() as session:
        row=session.get(RoomModel,room['id']);row.capacity=0
        with pytest.raises(IntegrityError): session.commit()
        session.rollback()
    with db() as session: assert session.get(RoomModel,room['id']).capacity==4
