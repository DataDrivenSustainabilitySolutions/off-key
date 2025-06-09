from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware

from .db.base import engine
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


app = FastAPI(title=settings.APP_NAME)

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
