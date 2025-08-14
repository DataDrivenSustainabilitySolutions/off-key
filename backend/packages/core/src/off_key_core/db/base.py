from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from off_key.core.config import settings
from off_key.core.logs import logger

# Synchronous Engine
engine = create_engine(
    settings.database_url,  # URL for the synchronous database
    echo=settings.DEBUG,  # Log SQL queries only in debug mode
    echo_pool=False,
    pool_pre_ping=True,  # Enable connection health checks
    pool_size=10,  # Number of connections to keep in the pool
    max_overflow=20,  # Allow additional connections beyond the pool size
)

# Synchronous Session Factory
SyncSessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,  # Disable autocommit for explicit transaction control
    autoflush=False,  # Disable autoflush to avoid unintended database writes
    expire_on_commit=False,  # Prevent objects from expiring after commit
)

# Asynchronous Engine
async_engine = create_async_engine(
    settings.async_database_url,  # URL for the asynchronous database
    echo=settings.DEBUG,  # Log SQL queries only in debug mode
    pool_pre_ping=True,  # Enable connection health checks
    pool_size=10,  # Number of connections to keep in the pool
    max_overflow=20,  # Allow additional connections beyond the pool size
)

# Asynchronous Session Factory
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    autocommit=False,  # Disable autocommit for explicit transaction control
    autoflush=False,  # Disable autoflush to avoid unintended database writes
    expire_on_commit=False,  # Prevent objects from expiring after commit
    class_=AsyncSession,  # Use AsyncSession for asynchronous operations
)

# Base class for declarative models
Base = declarative_base()


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
            await db.commit()  # Commit changes if no exceptions occur
        except Exception as e:
            await db.rollback()  # Rollback on errors
            logger.warning(f"Database transaction rolled back: {str(e)}")
            raise
        finally:
            await db.close()  # Ensure the session is closed


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
        db.commit()  # Commit changes if no exceptions occur
    except Exception as e:
        db.rollback()  # Rollback on errors
        logger.warning(f"Database transaction rolled back: {str(e)}")
        raise
    finally:
        db.close()  # Ensure the session is closed


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
            await db.close()  # Just close, don't commit


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
        db.close()  # Just close, don't commit
