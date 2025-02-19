from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db.base import engine
from .db.init_db import initialize_timescaledb
from .core.config import settings
from .api.v1.routes import router as v1_router
from .db.models import Base


app = FastAPI(title=settings.APP_NAME)


origins = [
    "http://localhost:3000",  # Add your frontend URL here
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Create timescale hypertable
initialize_timescaledb()

# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/info")
async def info():
    return settings.dict()


@app.get("/ping/{ping_input}")
async def ping(ping_input: str):
    return {"ping": ping_input}

@app.get("/data")
async def get_data():
    return [
        {"timestamp": datetime.now().isoformat(), "value": 10},
        {"timestamp": datetime.now().isoformat(), "value": 15},
        {"timestamp": datetime.now().isoformat(), "value": 8},
    ]


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
