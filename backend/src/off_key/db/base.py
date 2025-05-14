from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from off_key.core.config import settings

# Synchronous Engine
engine = create_engine(
    settings.database_url,  # URL for the synchronous database
    echo=True,  # Log SQL queries for debugging
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
    echo=False,  # Log SQL queries for debugging
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
        except Exception:
            await db.rollback()  # Rollback on errors
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
    except Exception:
        db.rollback()  # Rollback on errors
        raise
    finally:
        db.close()  # Ensure the session is closed
