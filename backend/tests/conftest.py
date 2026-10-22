"""Shared fixtures for Off-Key backend tests: sample results and database access."""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from tests.support.pipeline_database import pipeline_database  # noqa: F401

DATABASE_FIXTURES = frozenset({"disposable_database", "member_database"})


def pytest_collection_modifyitems(items):
    """Mark every test that reaches a database fixture, however indirectly."""
    for item in items:
        if DATABASE_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.postgres)


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_anomaly_result():
    """Create a sample anomaly result."""
    from off_key_mqtt_radar.models import AnomalyResult

    return AnomalyResult(
        anomaly_score=0.85,
        is_anomaly=True,
        severity="high",
        timestamp=datetime.now(UTC),
        model_info={"model_type": "isolation_forest"},
        raw_data={"cpu_usage": 95.5},
        topic="telemetry/charger-001/cpu",
        charger_id="charger-001",
        context={"static_conformal": {"phase": "ready", "p_value": 0.01}},
    )


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def disposable_database():
    """Give each real database test its own database on the CI fixture server."""
    value = os.getenv("TEST_SCHEMA_DATABASE_URL")
    if not value:
        pytest.skip("Requires an explicitly supplied disposable PostgreSQL server")
    url = make_url(value).set(drivername="postgresql+psycopg2")
    name = "offkey_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = create_engine(url.set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


@pytest_asyncio.fixture
async def member_database():
    """Isolate real account lifecycle tests in a disposable PostgreSQL schema."""
    from off_key_core.db.models import RememberedSession, User
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    url = os.getenv("TEST_SCHEMA_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SCHEMA_DATABASE_URL must point to a disposable database")
    schema = "members_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(RememberedSession.__table__.create)
        yield engine, async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


@pytest.fixture
def mock_async_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_async_session):
    """Create a mock session factory."""
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_async_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory
