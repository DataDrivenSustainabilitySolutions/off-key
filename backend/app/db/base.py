from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import settings

engine = create_engine(settings.database_url)

# Create an async session factory
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


# Dependency function for async session
async def get_db():
    """Dependency for async database sessions."""
    async with AsyncSessionLocal() as db:
        yield db
        await db.commit()  # Optional, commit if necessary
