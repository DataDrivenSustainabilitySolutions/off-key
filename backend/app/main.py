from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .schemas import users
from .db.crud import auth
from .db.base import engine, get_db_async
from .core.config import settings
from .api.v1.routes import router as v1_router
from .db.models import Base


@asynccontextmanager
async def lifespan(application: FastAPI):
    await create_admin_user()
    yield

async def create_admin_user():
    admin_email = settings.ADMIN_EMAIL
    admin_password = settings.ADMIN_PASSWORD
    if not admin_email or not admin_password:
        print("No admin credentials provided.")
        return

    try:
        if not await auth.get_user_by_email(admin_email):
            admin_data = users.UserCreate(email=admin_email, password=admin_password)
            await auth.create_user(admin_data, is_superuser=True)
            # Optionally, mark admin as active immediately.
            await auth.update_user_active_status(admin_email, True)
            print(f"Admin user created: {admin_email}")
        else:
            print("Admin user already exists.")
    except ValueError:
        print("ValueError")

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)


origins = ["http://localhost:8000", "http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create database tables
Base.metadata.create_all(bind=engine)

# Include versioned API routes
app.include_router(v1_router, prefix="/v1", tags=["v1"])

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/info")
async def info():
    """
    Returns environment variables.
    """
    return settings.dict()
