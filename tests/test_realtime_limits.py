"""Malformed socket input, capacity recovery and ticket consumption races."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier

from fastapi import HTTPException
import pytest
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from services import realtime
from tests.lib import api
from tests.test_realtime import receive, user_socket


@pytest.mark.parametrize('payload', ['not-json', 'null', '[]', '42', '"text"', '{}', '{"action":"unknown"}', b'not-text'])
def test_authenticated_socket_rejects_malformed_frames_and_recovers(network, factory, payload):
    user = factory.user()
    with user_socket(network, user) as socket:
        socket.send(payload)
        error = receive(socket, 'error')
        assert error['detail']
        socket.send(json.dumps({'action': 'ping'}))
        assert receive(socket, 'pong') == {'type': 'pong'}


def test_realtime_global_connection_limit_is_released_after_disconnect(network, factory, monkeypatch):
    monkeypatch.setattr(realtime, 'MAX_CONNECTIONS', 1)
    user = factory.user()
    with user_socket(network, user):
        ticket = api(network.client, 'POST', '/socket-ticket', user=user)['ticket']
        with pytest.raises(InvalidStatus) as denied:
            connect(network.ws + '/api/v1/ws?ticket=' + ticket)
        assert denied.value.response.status_code == 403
    # The ordinary socket fixture waits for a ready response; allow the loop
    # to finish its previous disconnect before attempting a new reservation.
    import time
    deadline = time.monotonic() + 2
    while realtime.realtime_hub.by_ip and time.monotonic() < deadline:
        time.sleep(.01)
    with user_socket(network, user) as reopened:
        reopened.send('{"action":"ping"}')
        assert receive(reopened, 'pong') == {'type': 'pong'}


def test_utf8_socket_size_is_enforced_in_bytes(network, factory):
    user = factory.user()
    with user_socket(network, user) as socket:
        socket.send('ب' * (realtime.MAX_MESSAGE_BYTES // 2 + 1))
        with pytest.raises(ConnectionClosed) as closed:
            socket.recv(timeout=2)
        assert closed.value.rcvd.code == 1009


def test_pending_ticket_capacity_recovers_after_consumption_and_expiry(monkeypatch):
    monkeypatch.setattr(realtime, 'MAX_TICKETS', 2)
    now = [100.0]
    monkeypatch.setattr(realtime.time, 'monotonic', lambda: now[0])
    tickets = realtime.SocketTickets()
    first, second = tickets.issue('first'), tickets.issue('second')
    with pytest.raises(HTTPException) as full:
        tickets.issue('third')
    assert full.value.status_code == 503
    assert tickets.consume(first) == 'first' and tickets.consume(first) is None
    third = tickets.issue('third')
    now[0] += realtime.TICKET_TTL_SECONDS
    assert tickets.consume(second) is None and tickets.consume(third) is None
    fresh = tickets.issue('fresh')
    assert tickets.consume(fresh) == 'fresh'
    tickets.clear()
    assert tickets.values == {}


def test_concurrent_single_use_ticket_has_exactly_one_consumer():
    tickets = realtime.SocketTickets()
    ticket = tickets.issue('one-authenticated-token')
    barrier = Barrier(8)
    def consume(_):
        barrier.wait(timeout=3)
        return tickets.consume(ticket)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(consume, range(8)))
    assert values.count('one-authenticated-token') == 1 and values.count(None) == 7
    assert tickets.values == {}
