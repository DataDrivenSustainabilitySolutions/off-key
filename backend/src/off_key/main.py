from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from off_key.core.config import settings

from .core.logs import logger
from .schemas import user
from .db.crud import auth
from .db.base import engine, AsyncSessionLocal
from .api.v1.routes import router as v1_router
from .db.models import Base


app = FastAPI(title=settings.APP_NAME)


origins = ["http://localhost:8000", "http://localhost:5173"]

# Enable CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow only specified origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


@app.get("/info")
async def info():
    """
    Returns environment variables.
    """
    return settings.dict()
