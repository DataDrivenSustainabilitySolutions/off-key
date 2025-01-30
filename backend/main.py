from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.api.auth.routes import router as auth_router
from backend.services.database import Database
import os

app = FastAPI()

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database initialization
db = Database(os.getenv("DATABASE_URL"))
db.create_tables()

# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
