import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.teas import router as TeasRouter
from controllers.groups import router as GroupsRouter
from controllers.user import router as UsersRouter
from controllers.sports import router as SportsRouter

tags = [
    {
        "name": "Groups Management",
        "description": "Operations related to groups for teas",
    },
    {
        "name": "Teas Management",
        "description": "Operations related to teas",
    },
    {
        "name": "Users Management",
        "description": "Operations related to users",
    },
    {
        "name": "Sports Management",
        "description": "Operations related to sports",
    },
]
app = FastAPI(
    title="Tea API", description="API for managing teas and groups", openapi_tags=tags
)
app.include_router(UsersRouter, prefix="/api/v1")
app.include_router(TeasRouter, prefix="/api/v1")
app.include_router(GroupsRouter, prefix="/api/v1")
app.include_router(SportsRouter, prefix="/api/v1")


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
