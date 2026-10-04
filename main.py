import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.groups import router as GroupsRouter
from controllers.auth import router as AuthRouter
from controllers.users import router as UsersRouter
from controllers.sports import router as SportsRouter
from controllers.cups import router as CupsRouter
from controllers.rooms import router as RoomsRouter
from controllers.messages import router as MessagesRouter
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
        "description": "Football cups, team entries and knockout brackets",
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
]
app = FastAPI(
    title="Modeer Almalaaeb API",
    description="API for organizing activities, groups and cups in Bahrain",
    openapi_tags=tags,
)
app.include_router(AuthRouter, prefix="/api/v1")
app.include_router(UsersRouter, prefix="/api/v1")
app.include_router(GroupsRouter, prefix="/api/v1")
app.include_router(SportsRouter, prefix="/api/v1")
app.include_router(CupsRouter, prefix="/api/v1")
app.include_router(RoomsRouter, prefix="/api/v1")
app.include_router(MessagesRouter, prefix="/api/v1")
app.include_router(RoomMembersRouter, prefix="/api/v1")
app.include_router(FriendsRouter, prefix="/api/v1")
app.include_router(GroupMembersRouter, prefix="/api/v1")
app.include_router(CupRosterRouter, prefix="/api/v1")


origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"ok": True}


@app.get("/")
def home():
    return {"message": "Hello World!"}
