import logging
import os

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET")

# The lifecycle worker starts and finishes rooms on time. With several workers
# or instances, set LIFECYCLE_WORKER=off on all but one.
LIFECYCLE_WORKER_ENABLED = os.getenv("LIFECYCLE_WORKER", "on").strip().lower() != "off"

# Browser origins allowed to call the API and to open the lobby socket
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")

# How long a started room's host may be offline before a connected player takes over
HOST_AWAY_GRACE_SECONDS = int(os.getenv("HOST_AWAY_GRACE_SECONDS", str(5 * 60 * 60)))


def require_settings():
    # Called by main.py before the app is built, so a misconfigured deploy fails
    # at boot instead of on the first login. Alembic and scripts.import_sports
    # import the models without calling this, so they only need DATABASE_URL.
    missing = [name for name, value in (("DATABASE_URL", DATABASE_URL), ("JWT_SECRET", JWT_SECRET)) if not value]
    if missing:
        raise RuntimeError("Missing required environment variable(s): " + ", ".join(missing))
    # Only a warning: a short secret still works, but it is easier to guess
    if len(JWT_SECRET) < 32:
        logging.getLogger(__name__).warning("JWT_SECRET is shorter than 32 characters; use a longer random secret")
