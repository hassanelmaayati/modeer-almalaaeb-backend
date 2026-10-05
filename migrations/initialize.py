"""Initialize an explicitly selected, empty PostgreSQL schema atomically."""
import argparse
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def migration_config(connection=None, database_url=None):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def initialize_database(database_url, *, reset_existing=False):
    engine = create_engine(database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise ValueError("Database initialization requires PostgreSQL")
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(429001684)"))
            connection.exec_driver_sql("SET LOCAL search_path TO public")
            objects = connection.execute(
                text(
                    "SELECT relation.oid, relation.relname, relation.relkind, "
                    "relation.relispartition "
                    "FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND relation.relkind IN ('r', 'p', 'v', 'm') "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM pg_depend AS dependency "
                    "WHERE dependency.classid = 'pg_class'::regclass "
                    "AND dependency.objid = relation.oid "
                    "AND dependency.deptype = 'e') "
                    "ORDER BY relation.relname"
                )
            ).all()
            if reset_existing:
                views = [relation.relname for relation in objects if relation.relkind in ('v', 'm')]
                if views:
                    raise ValueError(
                        "Initialization requires an empty schema; existing views: "
                        + ", ".join(views)
                    )
                partitions = [
                    relation.relname for relation in objects
                    if relation.relkind == 'p' or relation.relispartition
                ]
                if partitions:
                    raise ValueError(
                        "Reset refuses partitioned tables and partitions: "
                        + ", ".join(partitions)
                    )
                if objects:
                    dependencies = connection.execute(
                        text(
                            "SELECT namespace.nspname, relation.relname "
                            "FROM pg_depend AS dependency "
                            "JOIN pg_class AS relation ON relation.oid = dependency.objid "
                            "JOIN pg_namespace AS namespace "
                            "ON namespace.oid = relation.relnamespace "
                            "WHERE dependency.classid = 'pg_class'::regclass "
                            "AND dependency.refclassid = 'pg_class'::regclass "
                            "AND dependency.refobjid = ANY(CAST(:table_oids AS oid[])) "
                            "AND dependency.deptype IN ('a', 'i', 'P', 'S') "
                            "AND namespace.nspname != 'public' "
                            "AND namespace.nspname != 'information_schema' "
                            "AND left(namespace.nspname, 3) != 'pg_' "
                            "ORDER BY namespace.nspname, relation.relname"
                        ),
                        {"table_oids": [relation.oid for relation in objects]},
                    ).all()
                    if dependencies:
                        raise ValueError(
                            "Reset refuses automatic dependencies in other schemas: "
                            + ", ".join(f"{schema}.{name}" for schema, name in dependencies)
                        )
                quote = connection.dialect.identifier_preparer.quote
                tables = [
                    f"{quote('public')}.{quote(relation.relname)}" for relation in objects
                ]
                if tables:
                    # Dropping together handles application foreign keys. RESTRICT
                    # refuses external dependencies after the automatic-dependency check.
                    connection.exec_driver_sql("DROP TABLE " + ", ".join(tables))
            elif objects:
                raise ValueError(
                    "Initialization requires an empty schema; existing objects: "
                    + ", ".join(relation.relname for relation in objects)
                )
            config = migration_config(connection=connection)
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--reset-existing",
        action="store_true",
        help="drop non-extension tables in public and their data before initializing",
    )
    args = parser.parse_args()
    initialize_database(args.database_url, reset_existing=args.reset_existing)
    print("Empty database initialized successfully.")


if __name__ == "__main__":
    main()
