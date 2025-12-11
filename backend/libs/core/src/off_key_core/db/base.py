import threading

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Lazy initialization to avoid triggering Settings() on import
# This allows modules to import db/base.py without needing all env vars
_engine = None
_async_engine = None
_SyncSessionLocal = None
_AsyncSessionLocal = None
_logger = None

# Thread-safety locks for lazy initialization
_engine_lock = threading.Lock()
_async_engine_lock = threading.Lock()
_sync_session_lock = threading.Lock()
_async_session_lock = threading.Lock()
_logger_lock = threading.Lock()


def _get_settings():
    """Lazy import to avoid circular dependency and early Settings instantiation."""
    from ..config.config import settings

    return settings


def _get_logger():
    """Lazy import for logger (thread-safe)."""
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                from ..config.logs import logger

                _logger = logger
    return _logger


def get_engine():
    """Get or create sync engine lazily (thread-safe)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                settings = _get_settings()
                _engine = create_engine(
                    settings.database_url,
                    echo=settings.DEBUG,
                    echo_pool=False,
                    pool_pre_ping=True,
                    pool_size=10,
                    max_overflow=20,
                )
    return _engine


def get_async_engine():
    """Get or create async engine lazily (thread-safe)."""
    global _async_engine
    if _async_engine is None:
        with _async_engine_lock:
            if _async_engine is None:
                settings = _get_settings()
                _async_engine = create_async_engine(
                    settings.async_database_url,
                    echo=settings.DEBUG,
                    pool_pre_ping=True,
                    pool_size=10,
                    max_overflow=20,
                )
    return _async_engine


def get_sync_session_local():
    """Get or create sync session factory lazily (thread-safe)."""
    global _SyncSessionLocal
    if _SyncSessionLocal is None:
        with _sync_session_lock:
            if _SyncSessionLocal is None:
                _SyncSessionLocal = sessionmaker(
                    bind=get_engine(),
                    autocommit=False,
                    autoflush=False,
                    expire_on_commit=False,
                )
    return _SyncSessionLocal


def get_async_session_local():
    """Get or create async session factory lazily (thread-safe)."""
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        with _async_session_lock:
            if _AsyncSessionLocal is None:
                _AsyncSessionLocal = sessionmaker(
                    bind=get_async_engine(),
                    autocommit=False,
                    autoflush=False,
                    expire_on_commit=False,
                    class_=AsyncSession,
                )
    return _AsyncSessionLocal


# Backward-compatible proxies that defer initialization until first use
class _EngineProxy:
    """Proxy that lazily creates engine on first attribute access."""

    def __getattr__(self, name):
        return getattr(get_engine(), name)

    def __repr__(self) -> str:
        return repr(get_engine())


class _AsyncEngineProxy:
    """Proxy that lazily creates async engine on first attribute access."""

    def __getattr__(self, name):
        return getattr(get_async_engine(), name)

    def __repr__(self) -> str:
        return repr(get_async_engine())


class _SessionFactoryProxy:
    """Proxy that lazily creates sync session factory on first use."""

    def __call__(self):
        return get_sync_session_local()()

    def __getattr__(self, name):
        return getattr(get_sync_session_local(), name)

    def __repr__(self) -> str:
        return repr(get_sync_session_local())


class _AsyncSessionFactoryProxy:
    """Proxy that lazily creates async session factory on first use."""

    def __call__(self):
        return get_async_session_local()()

    def __getattr__(self, name):
        return getattr(get_async_session_local(), name)

    def __repr__(self) -> str:
        return repr(get_async_session_local())


# Backward compatible exports - these proxies defer initialization
engine = _EngineProxy()
async_engine = _AsyncEngineProxy()
SyncSessionLocal = _SessionFactoryProxy()
AsyncSessionLocal = _AsyncSessionFactoryProxy()

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
            _get_logger().warning(f"Database transaction rolled back: {str(e)}")
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
        _get_logger().warning(f"Database transaction rolled back: {str(e)}")
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
