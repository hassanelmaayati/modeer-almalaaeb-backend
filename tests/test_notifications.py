from models.notification import NotificationModel
from tests.lib import api


def test_notifications_are_user_owned_persisted_paginated_and_read_idempotently(client,factory,db):
    first,second=factory.user(),factory.user()
    with db() as session:
        rows=[NotificationModel(user_id=first['id'],kind='group.invitation',target={'type':'group','id':number+1},text=f'Invitation {number}') for number in range(3)]
        other=NotificationModel(user_id=second['id'],kind='room.update',target={'type':'room','id':1},text='Other notice')
        session.add_all([*rows,other]);session.commit()
        ids=[row.id for row in rows];other_id=other.id
    first_page=api(client,'GET','/notifications',user=first,params={'limit':2})
    assert first_page['unread_count']==3 and [row['id'] for row in first_page['items']]==ids[::-1][:2]
    assert all('user_id' not in row for row in first_page['items'])
    older=api(client,'GET','/notifications',user=first,params={'before':ids[1]})
    assert [row['id'] for row in older['items']]==[ids[0]] and older['unread_count']==3
    api(client,'PATCH',f'/notifications/{other_id}',user=first,body={'read':True},expected=404)
    marked=api(client,'PATCH',f'/notifications/{ids[1]}',user=first,body={'read':True})
    again=api(client,'PATCH',f'/notifications/{ids[1]}',user=first,body={'read':True})
    assert marked['read_at'] and marked['read_at']==again['read_at']
    unread=api(client,'GET','/notifications',user=first,params={'unread_only':True})
    assert [row['id'] for row in unread['items']]==[ids[2],ids[0]] and unread['unread_count']==2
    api(client,'PATCH','/notifications',user=first,body={'read':True},expected=204)
    assert api(client,'GET','/notifications',user=first,params={'unread_only':True})=={'items':[],'unread_count':0}
    with db() as session:
        assert all(session.get(NotificationModel,identifier).read_at for identifier in ids)
        assert session.get(NotificationModel,other_id).read_at is None


def test_notification_invalid_input_and_auth_leave_rows_unchanged(client,factory,db):
    user=factory.user()
    for query in [{'limit':0},{'limit':101},{'before':0}]:
        api(client,'GET','/notifications',user=user,params=query,expected=422)
    api(client,'PATCH','/notifications',user=user,body={'read':False},expected=422)
    api(client,'GET','/notifications',expected=401)
    with db() as session: assert session.query(NotificationModel).count()==0
