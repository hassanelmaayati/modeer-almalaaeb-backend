from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from migrations.initialize import BASELINE_TABLES, LEGACY_HEAD, initialize_database, migration_config

HEAD = 'f1c8d3a6b9e2'


def upgrade(url):
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection=connection), 'head')
    finally:
        engine.dispose()


def test_fresh_initialization_builds_real_schema_and_matches_models(empty_database):
    initialize_database(empty_database)
    engine = create_engine(empty_database)
    with engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == BASELINE_TABLES | {'notifications', 'alembic_version'}
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
        from models.base import Base
        # Alembic treats PostgreSQL's multiline CASE formatting as an index change.
        # Its behavior is separately checked with actual inverse-pair inserts.
        include = lambda obj, name, kind, reflected, compared: name != 'uq_memberships_friend_pair'
        assert compare_metadata(MigrationContext.configure(connection, opts={'compare_type': True, 'compare_server_default': True, 'include_object': include}), Base.metadata) == []
        pair_ddl = connection.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname='uq_memberships_friend_pair'")).scalar_one()
        assert 'CREATE UNIQUE INDEX' in pair_ddl and pair_ddl.count('CASE') == 2 and 'other_user_id IS NOT NULL' in pair_ddl
        checks = {value['name'] for value in inspect(connection).get_check_constraints('messages')}
        assert checks == {'ck_messages_type', 'ck_messages_exactly_one_target', 'ck_messages_type_matches_target', 'ck_messages_no_self_message', 'ck_messages_body_not_blank'}
        indexes = {value['name'] for value in inspect(connection).get_indexes('memberships')}
        assert {'uq_memberships_user_group', 'uq_memberships_friend_pair', 'uq_memberships_room_position'} <= indexes
    engine.dispose()


def legacy_rows(url):
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,user_name,email,password,token_version) VALUES (1,'legacy-one','one@example.test','hash',7),(2,'legacy-two','two@example.test','hash',3)"))
        connection.execute(text("INSERT INTO sports(id,name) VALUES (1,'Swimming')"))
        connection.execute(text("INSERT INTO groups(id,owner_id,sports_id,name) VALUES (1,1,1,'Legacy group')"))
        connection.execute(text("INSERT INTO rooms(id,host_id,sport_id,title,starts_at,ends_at,capacity,slot_layout,district,public_area) VALUES (1,1,1,'Legacy room',now()+interval '1 day',now()+interval '2 days',4,'{}','capital','Manama')"))
        connection.execute(text("INSERT INTO cups(id,organizer_user_id,sport_id,name,rules,team_count,roster_limit,entries,fixtures) VALUES(1,1,1,'Legacy cup','Fair play',4,8,'[]','[]')"))
        connection.execute(text("INSERT INTO memberships(user_id,other_user_id,status,accepted) VALUES(1,2,'accepted',true)"))
        connection.execute(text("INSERT INTO messages(id,sender_id,recipient_id,type,body,client_request_id) VALUES(1,1,2,'direct','Preserve me','2ce22db3-8003-4f1a-a570-0f925450a214')"))
    engine.dispose()


def test_existing_upgrade_preserves_records_relationships_and_token_versions(empty_database):
    initialize_database(empty_database, upgrade=False)
    legacy_rows(empty_database)
    upgrade(empty_database)
    upgrade(empty_database)
    engine = create_engine(empty_database)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT user_name,token_version FROM users ORDER BY id')).all() == [('legacy-one', 7), ('legacy-two', 3)]
        assert connection.execute(text('SELECT sender_id,recipient_id,body,group_id FROM messages')).one() == (1, 2, 'Preserve me', None)
        assert connection.execute(text('SELECT user_id,other_user_id,status FROM memberships')).one() == (1, 2, 'accepted')
        assert connection.execute(text('SELECT owner_id,sports_id,name FROM groups')).one() == (1, 1, 'Legacy group')
        assert connection.execute(text('SELECT entries,fixtures,name FROM cups')).one() == ([], [], 'Legacy cup')
        assert connection.execute(text('SELECT count(*) FROM notifications')).scalar_one() == 0
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
    engine.dispose()


def test_initialization_refuses_partial_database_without_touching_data(empty_database):
    engine = create_engine(empty_database)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE sentinel(id int primary key, value text)'))
        connection.execute(text("INSERT INTO sentinel VALUES(1,'keep')"))
    with pytest.raises(ValueError, match='empty schema'):
        initialize_database(empty_database)
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == ['sentinel']
        assert connection.execute(text('SELECT * FROM sentinel')).one() == (1, 'keep')
    engine.dispose()


def test_initialization_rolls_back_ddl_and_version_on_failure(empty_database):
    with patch('migrations.initialize.command.upgrade', side_effect=RuntimeError('injected migration failure')):
        with pytest.raises(RuntimeError, match='injected migration failure'):
            initialize_database(empty_database)
    engine = create_engine(empty_database)
    with engine.connect() as connection:
        assert inspect(connection).get_table_names() == []
    engine.dispose()


@pytest.mark.parametrize('target', ['room', 'group', 'cup', 'friend', 'position'])
def test_duplicate_preflight_rejects_without_modifying_legacy_data(empty_database, target):
    initialize_database(empty_database, upgrade=False)
    legacy_rows(empty_database)
    engine = create_engine(empty_database)
    values = {
        'room': "(2,NULL,1,NULL,NULL,'pending',NULL)",
        'group': "(2,NULL,NULL,1,NULL,'pending',NULL)",
        'cup': "(2,NULL,NULL,1,1,'pending',NULL)",
        'friend': "(2,1,NULL,NULL,NULL,'pending',NULL)",
        'position': "(2,NULL,1,NULL,NULL,'accepted','slot-a')",
    }
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO memberships(user_id,other_user_id,room_id,group_id,cup_id,status,position) VALUES' + values[target]))
        if target == 'friend':
            pass  # The existing inverse pair is the conflicting row.
        elif target == 'position':
            connection.execute(text("INSERT INTO memberships(user_id,room_id,status,position) VALUES(1,1,'accepted','slot-a')"))
        else:
            connection.execute(text('INSERT INTO memberships(user_id,other_user_id,room_id,group_id,cup_id,status,position) VALUES' + values[target]))
    with pytest.raises(RuntimeError, match='Duplicate memberships'):
        upgrade(empty_database)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == LEGACY_HEAD
        assert 'group_id' not in {column['name'] for column in inspect(connection).get_columns('messages')}
        assert 'notifications' not in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM memberships')).scalar_one() == (2 if target == 'friend' else 3)
    engine.dispose()


def test_parallel_initialization_is_atomic_and_only_one_succeeds(empty_database):
    def attempt():
        try:
            initialize_database(empty_database)
            return 'initialized'
        except ValueError:
            return 'refused'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ['initialized', 'refused']
    engine = create_engine(empty_database)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
        assert set(inspect(connection).get_table_names()) == BASELINE_TABLES | {'notifications', 'alembic_version'}
    engine.dispose()


def test_populated_new_data_prevents_lossy_downgrade(database_url):
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(id,user_name,email,password) VALUES(1,'reader','reader@example.test','hash')"))
        connection.exec_driver_sql("INSERT INTO notifications(user_id,kind,target,text) VALUES(1,'invite','{\"type\":\"group\",\"id\":1}','Keep unread')")
    with pytest.raises(RuntimeError, match='discard notifications'):
        with engine.begin() as connection:
            command.downgrade(migration_config(connection=connection), LEGACY_HEAD)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT text FROM notifications')).scalar_one() == 'Keep unread'
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
    engine.dispose()


def test_downgrade_below_frozen_baseline_is_refused_without_changes(database_url):
    engine = create_engine(database_url)
    with pytest.raises(ValueError, match='below the frozen baseline'):
        with engine.begin() as connection:
            command.downgrade(migration_config(connection=connection), 'base')
    with engine.connect() as connection:
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == HEAD
        assert set(inspect(connection).get_table_names()) == BASELINE_TABLES | {'notifications', 'alembic_version'}
    engine.dispose()
