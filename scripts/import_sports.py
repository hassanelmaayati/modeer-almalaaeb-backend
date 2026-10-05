"""Add missing catalogue sports without changing existing sports or other data."""
import argparse
import os

from sqlalchemy import create_engine, insert, select, text

from data.sports_data import build_sports
from models.sport import SportModel


def import_sports(database_url):
    engine = create_engine(database_url, hide_parameters=True)
    try:
        if engine.dialect.name != 'postgresql':
            raise ValueError('Sports import requires PostgreSQL')
        with engine.begin() as connection:
            # Names have no unique constraint; serialize repeat/concurrent imports.
            connection.execute(text('SELECT pg_advisory_xact_lock(429001685)'))
            existing = set(connection.execute(select(SportModel.name)).scalars())
            missing = [{'name': sport.name, 'formats': sport.formats}
                       for sport in build_sports() if sport.name not in existing]
            if missing:
                connection.execute(insert(SportModel), missing)
            return len(missing)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', default=os.getenv('DATABASE_URL'),
                        help='Database URL; defaults to the DATABASE_URL environment variable')
    args = parser.parse_args()
    if not args.database_url:
        parser.error('Set DATABASE_URL or supply --database-url')
    try:
        added = import_sports(args.database_url)
    except Exception as error:
        # Connection exceptions may contain credentials; do not print their contents.
        parser.exit(1, f'Sports import failed ({type(error).__name__}). Verify connectivity and the migrated schema.\n')
    print(f'Imported {added} missing sports.')


if __name__ == '__main__':
    main()
