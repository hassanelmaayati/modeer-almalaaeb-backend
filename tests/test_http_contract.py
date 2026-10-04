import pytest
from tests.lib import api

PROTECTED = [
    ('POST','/auth/logout'),('POST','/auth/google/link'),('POST','/socket-ticket'),
    ('GET','/users/me'),('PUT','/users/me'),('POST','/groups'),('PUT','/groups/1'),
    ('GET','/groups/1/members'),('POST','/groups/1/members'),('PATCH','/groups/1/members/1'),
    ('POST','/rooms'),('PUT','/rooms/1'),('POST','/rooms/1/cancel'),
    ('POST','/rooms/1/members'),('PATCH','/rooms/1/members/1'),('DELETE','/rooms/1/members/me'),
    ('GET','/friends'),('POST','/friends'),('PATCH','/friends/1'),
    ('GET','/messages'),('GET','/messages/conversations'),('POST','/messages'),
    ('POST','/cups'),('PATCH','/cups/1'),('DELETE','/cups/1'),('POST','/cups/1/entries'),
    ('PUT','/cups/1/entries/1'),('POST','/cups/1/roster'),('PATCH','/cups/1/roster/1'),
    ('GET','/notifications'),('PATCH','/notifications'),('PATCH','/notifications/1'),
]


@pytest.mark.parametrize('method,path',PROTECTED)
def test_every_protected_http_operation_rejects_guest_before_mutation(client,db,method,path):
    response=client.request(method,'/api/v1'+path,json={})
    assert response.status_code==401,response.text
    from models.user import UserModel
    from models.message import MessageModel
    from models.notification import NotificationModel
    from models.membership import MembershipModel
    with db() as session:
        for model in (UserModel,MessageModel,NotificationModel,MembershipModel):
            assert session.query(model).count()==0


def test_public_routes_return_real_empty_database_and_health(client):
    assert client.get('/health').json()=={'ok':True}
    assert client.get('/').json()=={'message':'Hello World!'}
    for route in ['/sports','/groups','/rooms','/cups']:
        assert api(client,'GET',route)==[]
    specification=client.get('/openapi.json').json()
    assert '/api/v1/notifications' in specification['paths'] and '/api/v1/socket-ticket' in specification['paths']
