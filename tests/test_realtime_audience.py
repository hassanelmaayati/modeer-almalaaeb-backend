"""Per-user ticket limits, audience-only token checks and the proxy-aware start command."""
from pathlib import Path
from fastapi import HTTPException

from services import realtime


def ticket(client, user):
    return client.post('/api/v1/socket-ticket', headers=user['headers'])


def test_one_user_cannot_use_up_the_shared_ticket_pool(client, factory):
    greedy, other = factory.user(), factory.user()
    issued = [ticket(client, greedy) for _ in range(realtime.MAX_TICKETS_PER_USER)]
    assert all(response.status_code == 200 for response in issued)
    limited = ticket(client, greedy)
    assert limited.status_code == 429 and 'Too many' in limited.json()['detail']
    # Everyone else is unaffected, and the global cap still protects the whole pool
    assert ticket(client, other).status_code == 200


def test_used_and_expired_tickets_free_a_users_slots(client, factory):
    user = factory.user()
    issued = [ticket(client, user).json()['ticket'] for _ in range(realtime.MAX_TICKETS_PER_USER)]
    assert ticket(client, user).status_code == 429
    assert realtime.tickets.consume(issued[0])
    assert ticket(client, user).status_code == 200
    assert ticket(client, user).status_code == 429
    for key in issued[1:3]:
        token, _, user_id = realtime.tickets.values[key]
        realtime.tickets.values[key] = (token, 0, user_id)
    assert ticket(client, user).status_code == 200


def test_only_sockets_in_an_events_audience_are_checked(configured_app, monkeypatch):
    checked = []
    def fake_user_from_token(db, token):
        checked.append(token)
        if token == 't3':
            raise HTTPException(status_code=401, detail='revoked')
    monkeypatch.setattr(realtime, 'user_from_token', fake_user_from_token)
    connections = [realtime.Connection(socket=f's{number}', user_id=number, token=f't{number}', token_version=0) for number in (1, 2, 3, 4)]
    events = [realtime.user_event([1, 3], {'type': 'first'}), realtime.user_event([4], {'type': 'second'})]
    deliveries, revoked = realtime._allowed_deliveries(events, connections)
    assert checked == ['t1', 't3', 't4']
    assert [(connection.user_id, payload['type']) for connection, payload in deliveries] == [(1, 'first'), (4, 'second')]
    assert revoked == {connections[2]}


def test_no_events_mean_no_checks(configured_app, monkeypatch):
    monkeypatch.setattr(realtime, 'user_from_token', lambda db, token: (_ for _ in ()).throw(AssertionError('checked')))
    assert realtime._allowed_deliveries([], [realtime.Connection(socket='s', user_id=1, token='t', token_version=0)]) == ([], set())


def test_the_container_trusts_proxy_headers_so_per_ip_limits_see_real_clients():
    command = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text()
    assert '--proxy-headers' in command and '--forwarded-allow-ips' in command and '--workers 1' in command
