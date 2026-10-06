"""Independent PostgreSQL fixtures configured before any application import."""
import os
from pathlib import Path
import sys
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from postgres_cluster import TemporaryPostgres
from tests.offline_network import blocked_attempts, install

_cluster = None


def pytest_sessionstart(session):
    global _cluster
    install()
    _cluster = TemporaryPostgres().start()
    os.environ.update(DATABASE_URL=_cluster.url, JWT_SECRET='modeer-isolated-backend-test-secret-2026',
                      LIFECYCLE_WORKER='off', GOOGLE_CLIENT_ID='isolated-client',
                      CORS_ORIGINS='http://localhost:5174,http://127.0.0.1:5174',
                      PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True


def pytest_sessionfinish(session, exitstatus):
    if _cluster is not None:
        _cluster.stop()


@pytest.fixture(autouse=True)
def fail_on_unexpected_external_network():
    before = len(blocked_attempts())
    yield
    unexpected = blocked_attempts()[before:]
    if unexpected:
        pytest.fail(f'Unexpected external networking was blocked: {unexpected}')


@pytest.fixture(scope='session')
def pg_cluster():
    return _cluster


@pytest.fixture
def empty_database(pg_cluster):
    url = pg_cluster.create_database()
    yield url
    pg_cluster.drop_database(url)


@pytest.fixture
def database_url(empty_database):
    from migrations.initialize import initialize_database
    initialize_database(empty_database)
    return empty_database


@pytest.fixture
def db(database_url):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autocommit=False, autoflush=False)
    yield factory
    engine.dispose()


@pytest.fixture(autouse=True)
def cheap_test_passwords(monkeypatch):
    from passlib.context import CryptContext
    import models.user
    monkeypatch.setattr(models.user, 'pwd_context', CryptContext(
        schemes=['bcrypt_sha256', 'bcrypt'], deprecated='auto',
        bcrypt_sha256__rounds=4, bcrypt__rounds=4,
    ))


@pytest.fixture
def configured_app(db, monkeypatch):
    import database
    import main
    from services import lobby, lobby_events
    from controllers import lobby_ws
    monkeypatch.setattr(main, 'LIFECYCLE_WORKER_ENABLED', False)
    monkeypatch.setattr(database, 'SessionLocal', db)
    try:
        from services import realtime
        monkeypatch.setattr(realtime, 'session_factory', db)
        monkeypatch.setattr(realtime, 'realtime_hub', realtime.RealtimeHub())
        monkeypatch.setattr(realtime, 'tickets', realtime.SocketTickets())
        if hasattr(main, 'realtime_hub'):
            monkeypatch.setattr(main, 'realtime_hub', realtime.realtime_hub)
    except ImportError:
        pass
    hub = lobby.InMemoryLobbyHub()
    monkeypatch.setattr(lobby, 'lobby_hub', hub)
    monkeypatch.setattr(lobby_events, 'lobby_hub', hub)
    monkeypatch.setattr(lobby_ws, 'lobby_hub', hub)
    monkeypatch.setattr(lobby_ws, 'open_total', 0)
    monkeypatch.setattr(lobby_ws, 'open_by_ip', {})

    def request_session():
        with db() as session:
            yield session
    main.app.dependency_overrides[database.get_db] = request_session
    try:
        yield main.app
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def client(configured_app):
    from fastapi.testclient import TestClient
    with TestClient(configured_app) as test_client:
        yield test_client


@pytest.fixture
def network(configured_app):
    import asyncio
    import socket
    import threading
    import time
    from types import SimpleNamespace
    import httpx
    import uvicorn
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(configured_app, host='127.0.0.1', port=port, log_level='warning'))
    network = SimpleNamespace(url=f'http://127.0.0.1:{port}', ws=f'ws://127.0.0.1:{port}', loop=None)
    async def serve():
        network.loop = asyncio.get_running_loop()
        await server.serve()
    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError('Isolated test HTTP server did not start')
        time.sleep(0.01)
    network.run = lambda task: asyncio.run_coroutine_threadsafe(task, network.loop).result(timeout=5)
    with httpx.Client(base_url=network.url, timeout=5) as network.client:
        try:
            yield network
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive(), 'Isolated server failed to shut down'


@pytest.fixture
def factory(db):
    from tests.lib import Factory
    return Factory(db)
