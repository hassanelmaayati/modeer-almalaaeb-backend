from datetime import datetime, timedelta, timezone
import jwt
import pytest
from sqlalchemy import select

from models.user import UserModel
from tests.lib import PASSWORD, api


def test_signup_login_profile_update_and_logout_are_persisted(client, db):
    registered = api(client, 'POST', '/auth/signup', body={'user_name': 'new_player', 'email': 'new@example.test', 'password': PASSWORD, 'bio': 'Striker', 'district': 'northern'}, expected=201)
    assert registered['user']['user_name'] == 'new_player'
    assert {'password', 'google_subject', 'token_version'}.isdisjoint(registered['user'])
    assert registered['user']['email'] == 'new@example.test'
    assert registered['user']['google_linked'] is False
    user = {'id': registered['user']['id'], 'headers': {'Authorization': 'Bearer ' + registered['token']}}
    with db() as session:
        stored = session.get(UserModel, user['id'])
        assert stored.password != PASSWORD and stored.verify_password(PASSWORD)
        assert stored.district == 'northern'
    logged_in = api(client, 'POST', '/auth/login', body={'email': 'new@example.test', 'password': PASSWORD})
    assert logged_in['user']['id'] == user['id']
    updated = api(client, 'PUT', '/users/me', user=user, body={'user_name': 'changed_player', 'bio': 'Midfielder', 'district': None})
    assert updated['user_name'] == 'changed_player' and updated['district'] is None
    assert api(client, 'GET', '/users/me', user=user)['bio'] == 'Midfielder'
    with db() as session:
        assert session.get(UserModel, user['id']).user_name == 'changed_player'
    public = api(client, 'GET', f"/users/{user['id']}")
    assert public['user_name'] == 'changed_player'
    private_fields = {'password', 'email', 'google_subject', 'google_linked', 'token_version'}
    assert private_fields.isdisjoint(public)
    profiles = api(client, 'GET', '/users')
    assert [item['id'] for item in profiles] == [user['id']]
    assert all(private_fields.isdisjoint(item) for item in profiles)
    api(client, 'POST', '/auth/logout', user=user, expected=204)
    api(client, 'GET', '/users/me', user=user, expected=401)
    with db() as session:
        assert session.get(UserModel, user['id']).token_version == 1
    relogin = api(client, 'POST', '/auth/login', body={'email': 'new@example.test', 'password': PASSWORD})
    assert relogin['token'] != logged_in['token']


@pytest.mark.parametrize('changes,status', [({'user_name':'ab'},422),({'email':'bad'},422),({'password':'short'},422),({'district':'mars'},422)])
def test_signup_rejects_invalid_input_without_creating_users(client, db, changes, status):
    body = {'user_name':'valid_player','email':'valid@example.test','password':PASSWORD, **changes}
    api(client,'POST','/auth/signup',body=body,expected=status)
    with db() as session:
        assert session.query(UserModel).count() == 0


@pytest.mark.parametrize('field', ['user_name', 'email'])
def test_signup_rejects_duplicates_without_creating_users(client, db, factory, field):
    first = factory.user('existing')
    body = {'user_name':'other_player','email':'other@example.test','password':PASSWORD}
    body[field] = first[field]
    api(client,'POST','/auth/signup',body=body,expected=400)
    with db() as session:
        assert session.query(UserModel).count() == 1


def test_login_and_profile_errors_do_not_mutate_existing_user(client, factory, db):
    user = factory.user()
    api(client,'POST','/auth/login',body={'email':user['email'],'password':'wrongpassword'},expected=401)
    api(client,'GET','/users/987654',expected=404)
    api(client,'PUT','/users/me',user=user,body={'user_name':user['user_name'],'district':'mars'},expected=422)
    with db() as session:
        assert session.get(UserModel,user['id']).district == 'capital'
        assert session.get(UserModel,user['id']).token_version == 0


@pytest.mark.parametrize('claims', [
    {'sub':'abc','ver':0}, {'sub':None,'ver':0}, {'sub':'1','ver':-1}, {'sub':'99999','ver':0},
    {'sub':'1'}, {'sub':'1','ver':0,'exp':1},
])
def test_invalid_claims_are_401_instead_of_server_errors(client, factory, claims):
    factory.user()
    body = {'exp':datetime.now(timezone.utc)+timedelta(hours=1), **claims}
    token = jwt.encode(body,'modeer-isolated-backend-test-secret-2026',algorithm='HS256')
    response = client.get('/api/v1/users/me',headers={'Authorization':'Bearer '+token})
    assert response.status_code == 401, response.text


def test_google_create_signin_link_and_collision_have_real_database_outcomes(client, db, factory, monkeypatch):
    import controllers.google_auth as google
    claims = {'sub':'google-subject-one','email':'google@example.test','email_verified':True,'picture':'https://example.test/photo.jpg'}
    monkeypatch.setattr(google,'verify_google_credential',lambda _: claims)
    created = api(client,'POST','/auth/google',body={'credential':'verified-fixture'},expected=201)
    signed = api(client,'POST','/auth/google',body={'credential':'verified-fixture'})
    assert signed['user']['id'] == created['user']['id']
    password_user = factory.user()
    claims.update(sub='google-subject-two',email=password_user['email'])
    api(client,'POST','/auth/google',body={'credential':'fixture'},expected=409)
    linked = api(client,'POST','/auth/google/link',user=password_user,body={'credential':'fixture'})
    assert linked['id'] == password_user['id']
    api(client,'POST','/auth/google/link',user=password_user,body={'credential':'fixture'},expected=409)
    other = factory.user()
    api(client,'POST','/auth/google/link',user=other,body={'credential':'fixture'},expected=409)
    with db() as session:
        assert session.get(UserModel,password_user['id']).google_subject == 'google-subject-two'
        assert session.query(UserModel).filter(UserModel.google_subject=='google-subject-one').count() == 1
        assert session.get(UserModel,other['id']).google_subject is None


@pytest.mark.parametrize('problem,status', [('unconfigured',503),('invalid',401),('unverified',401),('network',503)])
def test_google_verification_failures_create_no_account(client, db, monkeypatch, problem, status):
    import controllers.google_auth as google
    from google.auth.exceptions import GoogleAuthError
    if problem=='unconfigured':
        monkeypatch.setattr(google,'GOOGLE_CLIENT_ID',None)
    else:
        def verify(*args,**kwargs):
            if problem=='invalid': raise ValueError('invalid')
            if problem=='network': raise GoogleAuthError('offline')
            return {'email_verified':False}
        monkeypatch.setattr(google.id_token,'verify_oauth2_token',verify)
    api(client,'POST','/auth/google',body={'credential':'fixture'},expected=status)
    with db() as session:
        assert session.query(UserModel).count()==0


def test_user_list_pages_in_id_order(client,factory):
    ids=sorted(factory.user()['id'] for _ in range(3))
    assert [user['id'] for user in api(client,'GET','/users?limit=2')]==ids[:2]
    assert [user['id'] for user in api(client,'GET','/users?limit=2&offset=2')]==ids[2:]
    for query in ('limit=0','limit=101','offset=-1'):
        api(client,'GET',f'/users?{query}',expected=422)


@pytest.mark.parametrize('photo_url',['javascript:alert(1)','ftp://example.test/a.png','/relative.png','https://'])
def test_photo_urls_must_be_web_urls(client,factory,db,photo_url):
    user=factory.user()
    api(client,'PUT','/users/me',user=user,body={'user_name':user['user_name'],'photo_url':photo_url},expected=422)
    api(client,'POST','/groups',user=user,body={'name':'Team','sports_id':factory.sport()['id'],'photo_url':photo_url},expected=422)
    api(client,'POST','/auth/signup',body={'user_name':'new_player','email':'new@example.test','password':'password123','photo_url':photo_url},expected=422)
    with db() as session:
        assert session.get(UserModel,user['id']).photo_url != photo_url


def test_empty_photo_url_clears_the_photo(client,factory):
    user=factory.user(photo_url='https://example.test/old.png')
    updated=api(client,'PUT','/users/me',user=user,body={'user_name':user['user_name'],'photo_url':''})
    assert updated['photo_url'] is None
