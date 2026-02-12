from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..config.config import get_settings
from ..config.logs import logger

# Initialize database components
settings = get_settings()

# Synchronous Engine
engine = create_engine(
    settings.database_url,
    echo=settings.DEBUG,
    echo_pool=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Synchronous Session Factory
SyncSessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Asynchronous Engine
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Asynchronous Session Factory
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)

# Base class for declarative models
Base = declarative_base()


def get_engine():
    """Return the configured synchronous SQLAlchemy engine."""
    return engine


# Dependency for asynchronous database sessions
async def get_db_async():
    """
    Provides an asynchronous database session.
    Commits the transaction if no exceptions occur.
    Automatically closes the session when done.
    """
    async with AsyncSessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.warning(f"Database transaction rolled back: {str(e)}")
            raise
        finally:
            await db.close()


# Dependency for synchronous database sessions
def get_db_sync():
    """
    Provides a synchronous database session.
    Commits the transaction if no exceptions occur.
    Automatically closes the session when done.
    """
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Database transaction rolled back: {str(e)}")
        raise
    finally:
        db.close()


# Dependency for asynchronous database sessions without auto-commit
async def get_db_transactional():
    """
    Provides an asynchronous database session without auto-commit.
    Useful for complex transactions where manual commit/rollback control is needed.
    The caller is responsible for committing or rolling back the transaction.
    """
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()


# Dependency for synchronous database sessions without auto-commit
def get_db_sync_transactional():
    """
    Provides a synchronous database session without auto-commit.
    Useful for complex transactions where manual commit/rollback control is needed.
    The caller is responsible for committing or rolling back the transaction.
    """
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()
