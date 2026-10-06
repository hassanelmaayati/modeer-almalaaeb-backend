from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from models.base import Base
from models.notification import NotificationModel
from models.sport import SportModel
from scripts.import_sports import import_sports


def other_row_counts(session):
    return {table.name: session.scalar(select(func.count()).select_from(table))
            for table in Base.metadata.sorted_tables if table.name != 'sports'}


def test_fresh_import_creates_only_exact_catalogue_sports(database_url, db):
    assert import_sports(database_url) == 8
    with db() as session:
        rows = session.query(SportModel).order_by(SportModel.id).all()
        assert [(row.name, row.formats) for row in rows] == [
            ('Football', [{'key': '5v5', 'capacity': 10}, {'key': '7v7', 'capacity': 14}, {'key': '11v11', 'capacity': 22}]),
            ('Basketball', [{'key': '3v3', 'capacity': 6}, {'key': '5v5', 'capacity': 10}]),
            ('Tennis', [{'key': 'singles', 'capacity': 2}, {'key': 'doubles', 'capacity': 4}]),
            ('Swimming', None),
            ('Walking', None),
            ('Marathon', None),
            ('Cycling', None),
            ('Handball', None),
        ]
        assert all(count == 0 for count in other_row_counts(session).values())


def test_repeat_import_preserves_existing_catalogue_custom_sports_and_application_data(database_url, db, factory):
    sport = factory.sport('Football', formats=[{'key': 'existing-format', 'capacity': 4}])
    factory.sport('Climbing')
    user = factory.user()
    group = factory.group(user, sport)
    room = factory.room(user, sport)
    factory.member(user, group=group)
    factory.message(user, room=room)
    factory.persist(NotificationModel(user_id=user['id'], kind='existing.notice',
                    target={'type': 'room', 'id': room['id']}, text='Preserve this notice'))
    with db() as session:
        before = other_row_counts(session)
    assert import_sports(database_url) == 7
    with db() as session:
        identities = {row.name: row.id for row in session.query(SportModel)}
    assert import_sports(database_url) == 0
    with db() as session:
        assert {row.name: row.id for row in session.query(SportModel)} == identities
        assert session.get(SportModel, sport['id']).formats == sport['formats']
        assert other_row_counts(session) == before


def test_concurrent_imports_add_catalogue_once_without_duplicate_names(database_url, db):
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(import_sports, [database_url, database_url])) == [0, 8]
    with db() as session:
        assert session.query(SportModel).count() == 8
        assert session.scalar(select(func.count(func.distinct(SportModel.name)))) == 8


def test_import_failure_rolls_back_entire_catalogue_and_preserves_existing_data(database_url, db, factory):
    sentinel = factory.sport('Existing custom sport')
    with db() as session:
        session.execute(text("ALTER TABLE public.sports ADD CONSTRAINT test_no_tennis CHECK (name != 'Tennis')"))
        session.commit()
    with pytest.raises(DBAPIError):
        import_sports(database_url)
    with db() as session:
        assert [(row.id, row.name) for row in session.query(SportModel)] == [(sentinel['id'], sentinel['name'])]


def test_cli_uses_explicit_environment_and_repeated_execution_is_safe(database_url, db):
    environment = {**os.environ, 'DATABASE_URL': database_url, 'PYTHONDONTWRITEBYTECODE': '1'}
    for added in (8, 0):
        result = subprocess.run([sys.executable, '-m', 'scripts.import_sports'],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f'Imported {added} missing sports.'
    with db() as session:
        assert session.query(SportModel).count() == 8


def test_cli_connection_failure_does_not_echo_credentials():
    password = 'do-not-print-this-test-password'
    environment = {**os.environ, 'DATABASE_URL': f'postgresql+psycopg2://unused:{password}@127.0.0.1:1/unavailable',
                   'PYTHONDONTWRITEBYTECODE': '1'}
    result = subprocess.run([sys.executable, '-m', 'scripts.import_sports'],
                cwd=Path(__file__).resolve().parents[1], env=environment,
                capture_output=True, text=True, timeout=10)
    assert result.returncode == 1 and 'Sports import failed' in result.stderr
    assert password not in result.stdout + result.stderr
