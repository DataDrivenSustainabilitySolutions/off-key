from fastapi import FastAPI

from .core.config import settings
from .db.database import Base, engine
from .api.v1.routes import router as v1_router

app = FastAPI(title=settings.APP_NAME)

# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])

# Automatically create tables if they don't exist
Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/info")
async def info():
    return settings.dict()
