import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from controllers.teas import router as TeasRouter
from controllers.comments import router as CommentsRouter
from controllers.user import router as UsersRouter

tags = [
    {
        "name": "Comments Management",
        "description": "Operations related to comments for teas",
    },
    {
        "name": "Teas Management",
        "description": "Operations related to teas",
    },
    {
        "name": "Users Management",
        "description": "Operations related to users",
    },
]
app = FastAPI(
    title="Tea API", description="API for managing teas and comments", openapi_tags=tags
)
app.include_router(TeasRouter, prefix="/api")
app.include_router(CommentsRouter, prefix="/api")
app.include_router(UsersRouter, prefix="/api")

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
