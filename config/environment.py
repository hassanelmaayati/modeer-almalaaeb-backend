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


def require_settings():
    # Called by main.py before the app is built, so a misconfigured deploy fails
    # at boot instead of on the first login. Alembic and scripts.import_sports
    # import the models without calling this, so they only need DATABASE_URL.
    missing = [name for name, value in (("DATABASE_URL", DATABASE_URL), ("JWT_SECRET", JWT_SECRET)) if not value]
    if missing:
        raise RuntimeError("Missing required environment variable(s): " + ", ".join(missing))
