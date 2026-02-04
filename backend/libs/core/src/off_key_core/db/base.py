from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from functools import lru_cache

from ..config.app import get_app_settings
from ..config.database import get_database_settings
from ..config.logs import logger


@lru_cache(maxsize=1)
def get_engine():
    """Get or create sync engine lazily."""
    settings = get_database_settings()
    app_settings = get_app_settings()
    return create_engine(
        settings.database_url,
        echo=app_settings.DEBUG,
        echo_pool=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache(maxsize=1)
def get_async_engine():
    """Get or create async engine lazily."""
    settings = get_database_settings()
    app_settings = get_app_settings()
    return create_async_engine(
        settings.async_database_url,
        echo=app_settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache(maxsize=1)
def get_sync_session_local():
    """Get or create sync session factory lazily."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def get_async_session_local():
    """Get or create async session factory lazily."""
    return sessionmaker(
        bind=get_async_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
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
    session_factory = get_async_session_local()
    async with session_factory() as db:
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
    session_factory = get_sync_session_local()
    db = session_factory()
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
    session_factory = get_async_session_local()
    async with session_factory() as db:
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
    session_factory = get_sync_session_local()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
