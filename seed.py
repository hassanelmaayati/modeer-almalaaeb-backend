# seed.py
from sqlalchemy.orm import Session, sessionmaker
from data.sports_data import sports_list
from data.groups_data import groups_list
from data.rooms_data import rooms_list
from data.users_data import user_list
from data.cups_data import cups_list
from config.environment import DATABASE_URL
from sqlalchemy import create_engine, text
from models.base import Base  # import base model

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

try:
    if engine.dialect.name == "postgresql":
        # Rooms store the venue pin as a PostGIS point, so the extension must exist first
        # (the PostGIS package has to be installed on the server; creating it needs superuser rights)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        except Exception as error:
            raise SystemExit(
                "PostGIS is not available on this PostgreSQL server. Install it (Stack Builder > "
                f"Spatial Extensions > PostGIS), restart the server and run this again. ({error})"
            )

    print("Recreating database...")
    # Drop and recreate tables to ensure a clean slate
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    print("Seeding the database...")
    db = SessionLocal()

    db.add_all(user_list)
    db.commit()

    db.add_all(sports_list)
    db.commit()

    db.add_all(groups_list)
    db.commit()

    db.add_all(cups_list)
    db.commit()

    db.add_all(rooms_list)
    db.commit()

    db.close()

    print("Database seeding complete! 👋")
except Exception as e:
    print("An error occurred:", e)
