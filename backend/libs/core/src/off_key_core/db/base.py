from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..config.database import get_database_settings
from ..config.logs import logger
from ..config.runtime import get_runtime_settings


@lru_cache(maxsize=1)
def get_engine():
    """Return lazily-created sync SQLAlchemy engine."""
    db_settings = get_database_settings()
    runtime_settings = get_runtime_settings()
    return create_engine(
        db_settings.database_url,
        echo=runtime_settings.DEBUG,
        echo_pool=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache(maxsize=1)
def get_async_engine():
    """Return lazily-created async SQLAlchemy engine."""
    db_settings = get_database_settings()
    runtime_settings = get_runtime_settings()
    return create_async_engine(
        db_settings.async_database_url,
        echo=runtime_settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


@lru_cache(maxsize=1)
def get_sync_session_local():
    """Return lazily-created sync session factory."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@lru_cache(maxsize=1)
def get_async_session_local():
    """Return lazily-created async session factory."""
    return async_sessionmaker(
        bind=get_async_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


# Base class for declarative models
Base = declarative_base()


def reset_db_runtime_caches() -> None:
    """Clear DB runtime caches for tests/tooling.

    Disposal is best-effort. Caches are always cleared to keep reset behavior
    deterministic even if dispose raises.
    """
    sync_engine = get_engine() if get_engine.cache_info().currsize else None
    async_sync_engine = (
        get_async_engine().sync_engine
        if get_async_engine.cache_info().currsize
        else None
    )

    if sync_engine is not None:
        try:
            sync_engine.dispose()
        except Exception as exc:
            logger.warning(f"Failed to dispose sync engine during cache reset: {exc}")

    if async_sync_engine is not None:
        try:
            async_sync_engine.dispose()
        except Exception as exc:
            logger.warning(f"Failed to dispose async engine during cache reset: {exc}")

    get_sync_session_local.cache_clear()
    get_async_session_local.cache_clear()
    get_engine.cache_clear()
    get_async_engine.cache_clear()


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
        yield db


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
