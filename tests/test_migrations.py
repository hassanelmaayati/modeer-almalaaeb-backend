"""Exercise the committed baseline against isolated PostgreSQL/PostGIS databases."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from migrations.autogenerate import migration_options
from migrations.initialize import initialize_database, migration_config
from models.base import Base
from models.room import RoomModel


@pytest.fixture
def head():
    script = ScriptDirectory.from_config(migration_config())
    heads = script.get_heads()
    assert len(heads) == 1
    revision = script.get_revision(heads[0])
    assert revision.down_revision is None
    return heads[0]


@pytest.fixture
def migration_engine(empty_database):
    engine = create_engine(empty_database)
    try:
        yield engine
    finally:
        engine.dispose()


def application_tables(connection):
    extension_tables = set(connection.execute(text(
        "SELECT relation.relname FROM pg_class relation "
        "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
        "JOIN pg_depend dependency ON dependency.classid = 'pg_class'::regclass "
        "AND dependency.objid = relation.oid AND dependency.deptype = 'e' "
        "JOIN pg_extension extension ON dependency.refclassid = 'pg_extension'::regclass "
        "AND dependency.refobjid = extension.oid "
        "WHERE namespace.nspname = 'public'"
    )).scalars())
    return set(inspect(connection).get_table_names(schema="public")) - extension_tables


def assert_current_schema(connection, head):
    assert application_tables(connection) == set(Base.metadata.tables) | {"alembic_version"}
    assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == head
    assert compare_metadata(
        MigrationContext.configure(connection, opts=migration_options(connection)), Base.metadata
    ) == []


def postgis_identity(connection):
    return connection.execute(text(
        "SELECT extension.oid, namespace.nspname, 'public.spatial_ref_sys'::regclass::oid, "
        "'public.geography_columns'::regclass::oid "
        "FROM pg_extension extension JOIN pg_namespace namespace "
        "ON namespace.oid = extension.extnamespace WHERE extension.extname = 'postgis'"
    )).one()


def insert_user(connection):
    return connection.execute(text(
        "INSERT INTO public.users(user_name,email,password) "
        "VALUES ('migration-player','migration@example.test','hash') RETURNING id"
    )).scalar_one()


def test_fresh_initialization_builds_schema_matching_all_models(empty_database, migration_engine, head):
    initialize_database(empty_database)
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert connection.execute(text(
            "SELECT srid FROM public.spatial_ref_sys WHERE srid = 4326"
        )).scalar_one() == 4326
        assert connection.execute(text("SELECT PostGIS_Version()")).scalar_one()


def test_standalone_alembic_commands_commit_upgrade_and_downgrade(
    empty_database, migration_engine, head
):
    # Supplying a URL exercises env.py's owned connection, as the CLI does.
    # Every check uses a different connection, so an uncommitted migration fails.
    command.upgrade(migration_config(database_url=empty_database), "head")
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        before = postgis_identity(connection)
    command.downgrade(migration_config(database_url=empty_database), "base")
    with migration_engine.connect() as connection:
        assert application_tables(connection) == {"alembic_version"}
        assert connection.execute(text("SELECT count(*) FROM public.alembic_version")).scalar_one() == 0
        assert postgis_identity(connection) == before
    command.upgrade(migration_config(database_url=empty_database), "head")
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert postgis_identity(connection) == before


def test_initialization_accepts_existing_postgis_without_recreating_it(empty_database, migration_engine, head):
    with migration_engine.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION postgis")
        before = postgis_identity(connection)
    initialize_database(empty_database)
    with migration_engine.connect() as connection:
        assert postgis_identity(connection) == before
        assert_current_schema(connection, head)


@pytest.mark.parametrize("changed_expression", [False, True])
def test_friend_pair_comparison_does_not_hide_missing_or_changed_index(
    empty_database, migration_engine, changed_expression
):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX public.uq_memberships_friend_pair")
        if changed_expression:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX uq_memberships_friend_pair ON public.memberships "
                "(user_id, other_user_id) WHERE other_user_id IS NOT NULL"
            )
        differences = compare_metadata(
            MigrationContext.configure(connection, opts=migration_options(connection)), Base.metadata
        )
        added = [index.name for operation, index in differences if operation == "add_index"]
        assert "uq_memberships_friend_pair" in added
        if changed_expression:
            removed = [index.name for operation, index in differences if operation == "remove_index"]
            assert "uq_memberships_friend_pair" in removed


def test_postgis_geography_round_trips_through_model(empty_database, migration_engine):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        user_id = insert_user(connection)
        sport_id = connection.execute(text(
            "INSERT INTO public.sports(name) VALUES ('Swimming') RETURNING id"
        )).scalar_one()
        room_id = connection.execute(text(
            "INSERT INTO public.rooms(host_id,sport_id,title,starts_at,ends_at,capacity,"
            "slot_layout,district,area,venue_point) VALUES (:user_id,:sport_id,'Map room',"
            "now()+interval '1 day',now()+interval '2 days',4,'{}'::jsonb,'capital','Manama',"
            "ST_GeogFromText('SRID=4326;POINT(50.586 26.223)')) RETURNING id"
        ), {"user_id": user_id, "sport_id": sport_id}).scalar_one()
        assert connection.execute(text(
            "SELECT ST_SRID(venue_point::geometry) FROM public.rooms WHERE id = :id"
        ), {"id": room_id}).scalar_one() == 4326
    with Session(migration_engine) as session:
        room = session.scalars(select(RoomModel).where(RoomModel.id == room_id)).one()
        assert room.venue_location == pytest.approx({"latitude": 26.223, "longitude": 50.586})


def test_explicit_reset_removes_public_tables_but_preserves_postgis_and_other_schemas(
    empty_database, migration_engine, head
):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        insert_user(connection)
        connection.exec_driver_sql("CREATE TABLE public.obsolete_table(value text)")
        connection.exec_driver_sql("CREATE SCHEMA reporting")
        connection.exec_driver_sql("CREATE TABLE reporting.records(value text)")
        connection.exec_driver_sql("INSERT INTO reporting.records VALUES ('keep')")
        connection.exec_driver_sql("CREATE SEQUENCE reporting.counter START 41")
        before = postgis_identity(connection)
    initialize_database(empty_database, reset_existing=True)
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert connection.execute(text("SELECT count(*) FROM public.users")).scalar_one() == 0
        assert connection.execute(text("SELECT value FROM reporting.records")).scalar_one() == "keep"
        assert connection.execute(text("SELECT nextval('reporting.counter')")).scalar_one() == 41
        assert postgis_identity(connection) == before


def test_initialization_refuses_existing_public_objects_without_touching_data(empty_database, migration_engine):
    with migration_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE public.sentinel(id int primary key, value text)")
        connection.exec_driver_sql("INSERT INTO public.sentinel VALUES (1,'keep')")
    with pytest.raises(ValueError, match="empty"):
        initialize_database(empty_database)
    with migration_engine.connect() as connection:
        assert application_tables(connection) == {"sentinel"}
        assert connection.execute(text("SELECT * FROM public.sentinel")).one() == (1, "keep")


@pytest.mark.parametrize("reset_existing", [False, True])
@pytest.mark.parametrize("view_kind", ["VIEW", "MATERIALIZED VIEW"])
def test_initialization_refuses_ordinary_public_views(
    empty_database, migration_engine, reset_existing, view_kind
):
    with migration_engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE {view_kind} public.sentinel AS SELECT 'keep'::text AS value")
    with pytest.raises(ValueError, match="view|empty"):
        initialize_database(empty_database, reset_existing=reset_existing)
    with migration_engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM public.sentinel")).scalar_one() == "keep"
        assert inspect(connection).get_table_names(schema="public") == []


def test_fresh_initialization_rolls_back_ddl_on_upgrade_failure(empty_database, migration_engine):
    def fail_upgrade(config, target):
        config.attributes["connection"].exec_driver_sql("CREATE TABLE public.failed(value text)")
        raise RuntimeError("injected migration failure")

    with patch("migrations.initialize.command.upgrade", side_effect=fail_upgrade):
        with pytest.raises(RuntimeError, match="injected migration failure"):
            initialize_database(empty_database)
    with migration_engine.connect() as connection:
        assert application_tables(connection) == set()


def test_reset_rolls_back_original_tables_rows_and_version_on_upgrade_failure(
    empty_database, migration_engine, head
):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        insert_user(connection)
        before = postgis_identity(connection)

    def fail_upgrade(config, target):
        connection = config.attributes["connection"]
        assert application_tables(connection) == set()
        connection.exec_driver_sql("CREATE TABLE public.failed(value text)")
        raise RuntimeError("injected migration failure")

    with patch("migrations.initialize.command.upgrade", side_effect=fail_upgrade):
        with pytest.raises(RuntimeError, match="injected migration failure"):
            initialize_database(empty_database, reset_existing=True)
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert connection.execute(text("SELECT user_name FROM public.users")).scalar_one() == "migration-player"
        assert postgis_identity(connection) == before


def test_reset_refuses_cross_schema_dependents_without_dropping_them(empty_database, migration_engine, head):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        user_id = insert_user(connection)
        connection.exec_driver_sql("CREATE SCHEMA reporting")
        connection.exec_driver_sql("CREATE TABLE reporting.records(user_id int REFERENCES public.users(id))")
        connection.execute(text("INSERT INTO reporting.records VALUES (:id)"), {"id": user_id})
    with pytest.raises(DBAPIError):
        initialize_database(empty_database, reset_existing=True)
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert connection.execute(text("SELECT user_id FROM reporting.records")).scalar_one() == user_id
        assert connection.execute(text("SELECT id FROM public.users")).scalar_one() == user_id


def test_reset_refuses_partitioned_table_without_dropping_cross_schema_partition(
    empty_database, migration_engine
):
    with migration_engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA reporting")
        connection.exec_driver_sql("CREATE TABLE public.parent(id int) PARTITION BY RANGE(id)")
        connection.exec_driver_sql(
            "CREATE TABLE reporting.records PARTITION OF public.parent FOR VALUES FROM (0) TO (10)"
        )
        connection.exec_driver_sql("INSERT INTO public.parent VALUES (1)")
    with pytest.raises(ValueError, match="partition"):
        initialize_database(empty_database, reset_existing=True)
    with migration_engine.connect() as connection:
        assert application_tables(connection) == {"parent"}
        assert connection.execute(text("SELECT id FROM public.parent")).scalar_one() == 1
        assert connection.execute(text("SELECT id FROM reporting.records")).scalar_one() == 1
        assert connection.execute(text(
            "SELECT EXISTS (SELECT 1 FROM pg_inherits WHERE inhrelid = 'reporting.records'::regclass "
            "AND inhparent = 'public.parent'::regclass)"
        )).scalar_one()


def test_parallel_initialization_is_atomic_and_only_one_succeeds(empty_database, migration_engine, head):
    def attempt():
        try:
            initialize_database(empty_database)
            return "initialized"
        except ValueError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2))) == ["initialized", "refused"]
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)


def test_empty_schema_downgrade_then_upgrade_rebuilds_baseline(empty_database, migration_engine, head):
    initialize_database(empty_database)
    with migration_engine.begin() as connection:
        before = postgis_identity(connection)
        command.downgrade(migration_config(connection=connection), "base")
        assert application_tables(connection) == {"alembic_version"}
        assert connection.execute(text("SELECT count(*) FROM public.alembic_version")).scalar_one() == 0
        assert postgis_identity(connection) == before
        command.upgrade(migration_config(connection=connection), "head")
    with migration_engine.connect() as connection:
        assert_current_schema(connection, head)
        assert postgis_identity(connection) == before
