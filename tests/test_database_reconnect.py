"""A dropped idle PostgreSQL connection must not break the next request."""
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool


def test_database_engine_reconnects_after_pooler_closes_idle_connection(database_url, monkeypatch):
    import config.environment
    monkeypatch.setattr(config.environment, 'DATABASE_URL', database_url)
    source = Path(__file__).resolve().parents[1] / 'database.py'
    spec = importlib.util.spec_from_file_location('isolated_database_reconnect', source)
    database = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(database)
    control = create_engine(database_url, poolclass=NullPool)
    try:
        with database.engine.connect() as connection:
            original_pid = connection.scalar(text('SELECT pg_backend_pid()'))
            assert connection.scalar(text('SELECT count(*) FROM sports')) == 0
        # Terminate the real backend only after its connection returns to the pool.
        with control.connect() as connection:
            assert connection.scalar(text('SELECT pg_terminate_backend(:pid)'),
                                     {'pid': original_pid}) is True
        with database.engine.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM sports')) == 0
            assert connection.scalar(text('SELECT pg_backend_pid()')) != original_pid
    finally:
        control.dispose()
        database.engine.dispose()
