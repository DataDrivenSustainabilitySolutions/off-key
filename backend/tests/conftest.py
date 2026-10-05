"""
Pytest configuration and fixtures for Off-Key backend tests.

Provides common fixtures for:
- Database mocking
- MQTT client mocking
- Service configuration
- Async test support
"""

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

# ============================================================================
# Async Support
# ============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Mock Fixtures
# ============================================================================


@pytest.fixture
def mock_mqtt_client():
    """Create a mock MQTT client."""
    client = AsyncMock()
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.set_message_handler = MagicMock()
    client.get_health_status = MagicMock(return_value={"status": "healthy"})
    return client


@pytest.fixture
def mock_database_writer():
    """Create a mock database writer."""
    writer = AsyncMock()
    writer.start = AsyncMock()
    writer.stop = AsyncMock()
    writer.write_anomaly = AsyncMock()
    writer.write_service_metrics = AsyncMock()
    writer.get_health_status = MagicMock(return_value={"status": "healthy"})
    return writer


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_telemetry_data() -> dict[str, float]:
    """Sample telemetry data for testing."""
    return {
        "cpu_usage": 45.5,
        "memory_usage": 1024.0,
        "temperature": 65.2,
        "voltage": 12.1,
    }


@pytest.fixture
def sample_mqtt_message():
    """Create a sample MQTT message."""
    from off_key_mqtt_radar.models import MQTTMessage

    return MQTTMessage(
        topic="device/evCharger/charger-001/cpu",
        payload=b'{"cpu_usage": 45.5, "temperature": 65.2}',
        qos=1,
        retain=False,
        timestamp=datetime.now(UTC),
    )


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
        topic="device/evCharger/charger-001/cpu",
        charger_id="charger-001",
        context={"processing_time_ms": 5.2},
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


# ============================================================================
# Environment Fixtures
# ============================================================================


@pytest.fixture
def clean_env(monkeypatch):
    """Clean environment for tests that depend on specific env vars."""
    env_vars_to_clear = [
        "RADAR_CHECKPOINT_SECRET",
        "RADAR_CHECKPOINT_DIR",
        "SERVICE_ID",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def test_env(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv("SERVICE_ID", "test-service")
    monkeypatch.setenv("RADAR_CHECKPOINT_DIR", "/tmp/test_checkpoints")
    monkeypatch.setenv("RADAR_CHECKPOINT_SECRET", "test-secret-key")
    return monkeypatch
