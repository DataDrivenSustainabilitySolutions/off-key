import asyncio
import datetime

from contextlib import asynccontextmanager
from fastapi import FastAPI

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .core.config import settings
from backend.app.clients.pionix import PionixClient

pionix_client = PionixClient(
    api_key=settings.PIONIX_KEY, user_agent=settings.PIONIX_USER_AGENT
)

def period_tasks():
    print("Hello")

scheduler = BackgroundScheduler()
scheduler.add_job(func=period_tasks, trigger=IntervalTrigger(minutes=10))

@asynccontextmanager
async def lifespan(application: FastAPI):
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="off-key", lifespan=lifespan)

@app.get("/")
async def root():
    return {"message": "Hello World"}
