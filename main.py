import asyncio
from contextlib import asynccontextmanager, suppress

from dotenv import load_dotenv

load_dotenv()

from config.environment import require_settings

# Before importing the controllers: database.py builds the engine at import time
require_settings()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.groups import router as GroupsRouter
from controllers.auth import router as AuthRouter
from controllers.google_auth import router as GoogleAuthRouter
from controllers.users import router as UsersRouter
from controllers.sports import router as SportsRouter
from controllers.cups import router as CupsRouter
from controllers.rooms import router as RoomsRouter
from config.environment import CORS_ORIGINS, LIFECYCLE_WORKER_ENABLED
from services.lifecycle import lifecycle_loop
from controllers.messages import router as MessagesRouter
from controllers.lobby_ws import router as LobbyWsRouter
from controllers.realtime_ws import router as RealtimeRouter
from controllers.notifications import router as NotificationsRouter
from controllers.player_ratings import router as PlayerRatingsRouter
from services import realtime
from controllers.memberships.room import router as RoomMembersRouter
from controllers.memberships.friends import router as FriendsRouter
from controllers.memberships.group import router as GroupMembersRouter
from controllers.memberships.cup import router as CupRosterRouter

tags = [
    {
        "name": "Auth",
        "description": "Sign up, sign in and sign out",
    },
    {
        "name": "Users Management",
        "description": "Profiles and player search",
    },
    {
        "name": "Groups Management",
        "description": "Operations related to social groups and teams",
    },
    {
        "name": "Sports Management",
        "description": "Operations related to sports",
    },
    {
        "name": "Cups Management",
        "description": "Cups for every competitive sport: entries, knockout brackets and races",
    },
    {
        "name": "Rooms Management",
        "description": "Operations related to rooms (scheduled activities)",
    },
    {
        "name": "Messages Management",
        "description": "Room chat, direct messages and the conversation list",
    },
    {
        "name": "Room Members Management",
        "description": "Operations related to room memberships",
    },
    {
        "name": "Friends Management",
        "description": "Friend requests and connections",
    },
    {
        "name": "Group Members Management",
        "description": "Group invitations and members",
    },
    {
        "name": "Cup Roster Management",
        "description": "Cup roster invitations",
    },
    {
        "name": "Realtime",
        "description": "Socket tickets for the signed-in user's live updates",
    },
    {
        "name": "Notifications",
        "description": "The signed-in user's notifications and read state",
    },
    {
        "name": "Player Ratings",
        "description": "Final 1-5 star ratings between players of a completed room, and profile averages",
    },
]


# Starts the worker that starts and finishes rooms, and stops it on shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = asyncio.create_task(lifecycle_loop()) if LIFECYCLE_WORKER_ENABLED else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        await realtime.realtime_hub.close()


app = FastAPI(
    lifespan=lifespan,
    title="Modeer Almalaaeb API",
    description="API for organizing activities, groups and cups in Bahrain",
    openapi_tags=tags,
)
app.include_router(AuthRouter, prefix="/api/v1")
app.include_router(GoogleAuthRouter, prefix="/api/v1")
app.include_router(UsersRouter, prefix="/api/v1")
app.include_router(GroupsRouter, prefix="/api/v1")
app.include_router(SportsRouter, prefix="/api/v1")
app.include_router(CupsRouter, prefix="/api/v1")
app.include_router(RoomsRouter, prefix="/api/v1")
app.include_router(MessagesRouter, prefix="/api/v1")
app.include_router(LobbyWsRouter, prefix="/api/v1")
app.include_router(RealtimeRouter, prefix="/api/v1")
app.include_router(NotificationsRouter, prefix="/api/v1")
app.include_router(PlayerRatingsRouter, prefix="/api/v1")
app.include_router(RoomMembersRouter, prefix="/api/v1")
app.include_router(FriendsRouter, prefix="/api/v1")
app.include_router(GroupMembersRouter, prefix="/api/v1")
app.include_router(CupRosterRouter, prefix="/api/v1")


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"ok": True}


@app.get("/")
def home():
    return {"message": "Hello World!"}
