# seed.py
from sqlalchemy.orm import Session, sessionmaker
from data.sports_data import sports_list
from data.groups_data import groups_list
from data.rooms_data import rooms_list
from data.users_data import user_list
from data.cups_data import cups_list
from config.environment import DATABASE_URL
from sqlalchemy import create_engine
from models.base import Base  # import base model

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

try:
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
