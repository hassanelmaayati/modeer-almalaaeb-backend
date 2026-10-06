"""Load demo data into a migrated, empty database.

Build the schema first, then seed:
    pipenv run python -m migrations.initialize --database-url "$DATABASE_URL"
    pipenv run python seed.py

The sports catalogue is imported first (scripts.import_sports). The rest of the
data is only added when there are no users yet, so seeding never mixes demo rows
into real data. Any failure rolls everything back and exits with status 1.
"""
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import models  # noqa: F401  registers every model before the session flushes
from config.environment import DATABASE_URL
from data.cups_data import build_cups
from data.groups_data import build_groups
from data.rooms_data import build_rooms
from data.users_data import build_users
from models.sport import SportModel
from models.user import UserModel
from scripts.import_sports import import_sports


class SeedRefused(Exception):
    pass


def seed(database_url):
    import_sports(database_url)
    engine = create_engine(database_url, hide_parameters=True)
    try:
        with Session(engine) as db, db.begin():
            if db.scalar(select(UserModel.id).limit(1)) is not None:
                raise SeedRefused("The database already has users; seed only an empty, migrated database")
            # Sport ids depend on the database, so the data looks them up by name
            sports = dict(db.execute(select(SportModel.name, SportModel.id)).all())

            users = build_users()
            db.add_all(users)
            db.flush()
            groups = build_groups(users, sports)
            db.add_all(groups)
            db.flush()
            db.add_all(build_cups(users, sports, groups))
            db.add_all(build_rooms(users, sports, groups))
    finally:
        engine.dispose()


def main():
    if not DATABASE_URL:
        sys.exit("Seeding failed: set DATABASE_URL")
    try:
        seed(DATABASE_URL)
    except SeedRefused as error:
        sys.exit(f"Seeding refused: {error}")
    except Exception as error:
        # Connection errors can include credentials, so only the error type is printed
        sys.exit(f"Seeding failed ({type(error).__name__}). Check DATABASE_URL and that migrations ran.")
    print("Database seeding complete.")


if __name__ == "__main__":
    main()
