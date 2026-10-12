"""Disposable real MQTT/Postgres environment shared by collection integration tests."""

import asyncio
import os

import pytest
import pytest_asyncio
from off_key_core.db.base import Base
from off_key_core.db.schema import bootstrap_schema
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("OFFKEY_COLLECTION_INTEGRATION") != "1",
    reason="Requires the isolated MQTT collection compose fixture",
)


async def until(check):
    async with asyncio.timeout(30):
        # External brokers and DB state have no local event to await.
        while not await check():  # noqa: ASYNC110
            await asyncio.sleep(0.1)


@pytest_asyncio.fixture
async def database(monkeypatch):
    # Fixed local fixture DSN: this test never uses application credentials or DB URLs.
    engine = create_async_engine(
        "postgresql+asyncpg://collection_test:collection-test-password@127.0.0.1:25432/collection_test"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(bootstrap_schema)
        # TRUNCATE CASCADE can drop Timescale foreign keys once chunks exist.
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(delete(table))
    try:
        yield engine, sessions
    finally:
        await engine.dispose()
