"""Initialize an explicitly selected, empty PostgreSQL schema atomically."""
import argparse
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

LEGACY_HEAD = "0a029e480f8f"
BASELINE = Path(__file__).with_name(f"baseline_{LEGACY_HEAD}.sql")
ROOT = Path(__file__).resolve().parents[1]
BASELINE_TABLES = {"users", "sports", "groups", "rooms", "cups", "memberships", "messages"}


def migration_config(connection=None, database_url=None):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def initialize_database(database_url, *, upgrade=True):
    engine = create_engine(database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("The frozen baseline requires PostgreSQL")
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(429001684)"))
            inspector = inspect(connection)
            objects = inspector.get_table_names() + inspector.get_view_names()
            if objects:
                raise ValueError("Initialization requires an empty schema; existing objects: " + ", ".join(sorted(objects)))
            connection.exec_driver_sql(BASELINE.read_text())
            if set(inspect(connection).get_table_names()) != BASELINE_TABLES:
                raise RuntimeError("Frozen baseline verification failed")
            message_columns = {item["name"] for item in inspect(connection).get_columns("messages")}
            if "group_id" in message_columns or "client_request_id" not in message_columns:
                raise RuntimeError("Frozen message baseline verification failed")
            config = migration_config(connection=connection)
            command.stamp(config, LEGACY_HEAD)
            if upgrade:
                command.upgrade(config, "head")
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    initialize_database(args.database_url, upgrade=not args.baseline_only)
    print("Empty database initialized successfully.")


if __name__ == "__main__":
    main()
