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
