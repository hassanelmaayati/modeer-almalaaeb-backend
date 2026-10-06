"""Slow/failed peers and selective logout cannot disrupt healthy devices."""
import asyncio

import pytest

from models.user import UserModel
from services import realtime


class Socket:
    def __init__(self, *, fail=False, slow=False, slow_close=False):
        self.fail, self.slow, self.slow_close = fail, slow, slow_close
        self.sent, self.closed = [], []
        self.delivered = asyncio.Event()

    async def send_json(self, payload):
        if self.fail:
            raise RuntimeError('Disconnected test peer')
        if self.slow:
            await asyncio.Event().wait()
        self.sent.append(payload)
        self.delivered.set()

    async def close(self, code):
        self.closed.append(code)
        if self.slow_close:
            await asyncio.Event().wait()


def token(user_id=1, version=0):
    row = UserModel(id=user_id, token_version=version)
    return row.generate_jwt()


@pytest.mark.parametrize('problem', ['failed-send', 'slow-send', 'slow-send-close'])
def test_realtime_send_is_bounded_and_healthy_devices_continue(monkeypatch, problem):
    monkeypatch.setattr(realtime, 'SEND_TIMEOUT_SECONDS', .04)
    async def exercise():
        hub = realtime.RealtimeHub()
        broken = Socket(fail=problem == 'failed-send', slow=problem != 'failed-send', slow_close=problem == 'slow-send-close')
        healthy = Socket()
        first, second = hub.connect(broken, 1, token()), hub.connect(healthy, 2, token(2))
        sends = asyncio.gather(hub.send(first, {'type': 'test'}), hub.send(second, {'type': 'test'}))
        await asyncio.wait_for(healthy.delivered.wait(), .2)
        await asyncio.wait_for(sends, .4)
        assert healthy.sent == [{'type': 'test'}] and healthy in hub.connections
        assert broken not in hub.connections and broken.closed == [1008]
        await hub.close()
        assert hub.connections == {} and healthy.closed == [1001]
    asyncio.run(exercise())


def test_logout_closes_only_old_versions_of_the_selected_user():
    async def exercise():
        hub = realtime.RealtimeHub()
        old, current, other = Socket(), Socket(), Socket()
        hub.connect(old, 1, token(1, 0))
        hub.connect(current, 1, token(1, 1))
        hub.connect(other, 2, token(2, 0))
        await hub.close_user(1, token_version=0)
        assert old.closed == [1008] and old not in hub.connections
        assert current.closed == [] and other.closed == []
        assert set(hub.connections) == {current, other}
        await hub.close_user(1)
        assert current.closed == [1008] and set(hub.connections) == {other}
        await hub.close()
    asyncio.run(exercise())


def test_reservations_enforce_global_and_ip_limits_and_release_is_idempotent(monkeypatch):
    monkeypatch.setattr(realtime, 'MAX_CONNECTIONS', 2)
    monkeypatch.setattr(realtime, 'MAX_CONNECTIONS_PER_IP', 1)
    hub = realtime.RealtimeHub()
    assert hub.reserve('first') and not hub.reserve('first')
    assert hub.reserve('second') and not hub.reserve('third')
    hub.release('first')
    hub.release('first')
    assert hub.reserve('third') and hub.by_ip == {'second': 1, 'third': 1}
    hub.release('second')
    hub.release('third')
    assert hub.by_ip == {}
