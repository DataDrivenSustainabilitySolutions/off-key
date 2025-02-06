import uvicorn
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import engine, SessionLocal
from .core.config import settings
from .api.v1.routes import router as v1_router
from backend.app.db.models import Chargers, Base

app = FastAPI(title=settings.APP_NAME)

# Create database tables
Base.metadata.create_all(bind=engine)

# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/info")
async def info():
    return settings.dict()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
