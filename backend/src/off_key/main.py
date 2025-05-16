from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from .core.config import settings
from .api.rate_limiter import limiter, rate_limit_exceeded_handler
from .core.logs import logger
from .schemas import user
from .db.crud import auth
from .db.base import engine, AsyncSessionLocal
from .api.v1.routes import router as v1_router
from .db.models import Base

# See https://github.com/pyca/bcrypt/issues/684#issuecomment-2465572106
import bcrypt
if not hasattr(bcrypt, '__about__'):
    bcrypt.__about__ = type('about', (object,), {'__version__': bcrypt.__version__})


@asynccontextmanager
async def lifespan(application: FastAPI):
    await create_admin_user()
    yield


async def create_admin_user():
    admin_email = settings.ADMIN_EMAIL
    admin_password = settings.ADMIN_PASSWORD
    if not admin_email or not admin_password:
        logger.warning("No admin credentials provided.")
        return

    async with AsyncSessionLocal() as db:
        try:
            if not await auth.get_user_by_email(admin_email, db):
                admin_data = user.UserCreate(email=admin_email, password=admin_password)
                await auth.create_user(admin_data, is_superuser=True, db=db)
                await auth.update_user_active_status(admin_email, True, db=db)
                logger.info(f"Admin user created: {admin_email}")
            else:
                logger.info("Admin user already exists.")
        except ValueError as e:
            logger.error(f"ValueError: {e}")
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            await db.rollback()  # Rollback in case of error


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(429, rate_limit_exceeded_handler)

origins = ["http://localhost:8000", "http://localhost:5173"]

# Enable SlowApi Middleware
app.add_middleware(SlowAPIMiddleware)

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
