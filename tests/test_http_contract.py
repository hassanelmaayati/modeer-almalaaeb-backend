import os
from pathlib import Path
import subprocess
import sys

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


@pytest.mark.parametrize('missing', ['DATABASE_URL', 'JWT_SECRET'])
def test_app_refuses_to_start_without_required_settings(missing):
    environment = {**os.environ, 'PYTHON_DOTENV_DISABLED': '1', 'DATABASE_URL': 'postgresql+psycopg2://unused@127.0.0.1:1/unused',
                   'JWT_SECRET': 'startup-check-secret', 'LIFECYCLE_WORKER': 'off'}
    environment.pop(missing)
    result = subprocess.run([sys.executable, '-c', 'import main'], cwd=Path(__file__).resolve().parents[1],
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert f'Missing required environment variable(s): {missing}' in result.stderr
