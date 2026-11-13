"""Reject invalid resource settings and enforce fleet admission with real locks."""

import asyncio

import pytest
from off_key_core.config.resource_budget import MEBIBYTE, parse_memory_bytes
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_tactic_middleware.config.config import (
    PoolConfig,
    RadarDefaultsConfig,
    TacticConfig,
    TacticSettings,
    clear_tactic_settings_caches,
)
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.form_pipeline import form_radar_config

pytestmark = pytest.mark.radar_integration


@pytest.mark.parametrize(
    "value", ["", "0", "0m", "-1m", "NaN", "inf", "bad", "1ib", "0.1b"]
)
def test_invalid_memory_limits_fail_validation_without_fallback(value):
    with pytest.raises(ValidationError):
        PoolConfig(memory_limit=value)


def test_binary_memory_units_have_exact_meaning():
    assert parse_memory_bytes("512m") == 512 * MEBIBYTE
    assert parse_memory_bytes("0.5 GiB") == 512 * MEBIBYTE
    assert parse_memory_bytes("1024") == 1024


def test_default_worker_and_pool_budgets_agree():
    config = TacticSettings().config
    assert (
        config.radar_defaults.memory_limit_mb
        == form_radar_config(
            None, ["telemetry/charger-sim-1/sine"], MQTTRadarConfig
        ).memory_limit_mb
        == 384
    )
    assert config.pool.memory_limit_bytes == 512 * MEBIBYTE
    assert config.radar_max_active_monitors == 20
    assert (
        config.radar_defaults.max_queue_size * config.radar_defaults.max_payload_bytes
        == 16 * MEBIBYTE
    )


@pytest.mark.parametrize("target", [512, 1024])
def test_internal_target_cannot_reach_the_pool_memory_limit(target):
    with pytest.raises(ValidationError, match="below its pool memory limit"):
        TacticConfig(
            pool=PoolConfig(),
            radar_defaults=RadarDefaultsConfig(memory_limit_mb=target),
        )


def _runtime_config(**fields):
    return form_radar_config(
        None, ["telemetry/charger-sim-1/sine"], MQTTRadarConfig, **fields
    )


@pytest.mark.parametrize(
    "factory", [_runtime_config, RadarDefaultsConfig], ids=["runtime", "defaults"]
)
def test_queue_payload_capacity_must_fit_inside_memory_target(factory):
    with pytest.raises(ValidationError, match="queued MQTT payload bytes"):
        factory(max_queue_size=1024, max_payload_bytes=1048576)


def test_operator_capacity_and_pool_limits_are_typed():
    settings = TacticSettings(
        TACTIC_RADAR_MAX_ACTIVE_MONITORS=4,
        TACTIC_RADAR_STOP_TIMEOUT_SECONDS=45,
        TACTIC_POOL_MEMORY_LIMIT="1g",
        TACTIC_POOL_RESTART_MONITORS=False,
        TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE=128,
        TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES=32768,
    )
    config = settings.config
    assert config.radar_max_active_monitors == 4
    assert config.radar_stop_timeout_seconds == 45
    assert config.pool.memory_limit_bytes == 1024 * MEBIBYTE
    assert config.pool.restart_monitors is False
    assert config.radar_defaults.max_queue_size == 128
    assert config.radar_defaults.max_payload_bytes == 32768
    with pytest.raises(ValidationError):
        TacticSettings(TACTIC_RADAR_MAX_ACTIVE_MONITORS=0)


@pytest.mark.asyncio
async def test_concurrent_monitor_admissions_share_real_database_capacity_lock(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    monkeypatch.setenv("TACTIC_RADAR_MAX_ACTIVE_MONITORS", "1")
    clear_tactic_settings_caches()
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def claim(name):
        async with sessions.begin() as session:
            orchestration = RadarOrchestrationService.__new__(RadarOrchestrationService)
            orchestration.session = session
            await orchestration._assert_topics_available(
                mqtt_topics=[f"telemetry/entity/{name}"], container_name=name
            )
            session.add(
                MonitoringService(
                    id=name,
                    container_name=name,
                    mqtt_topic=[f"telemetry/entity/{name}"],
                    status=True,
                    desired_state="running",
                    operational_stage="starting",
                )
            )
        return name

    try:
        outcomes = await asyncio.gather(
            claim("first"), claim("second"), return_exceptions=True
        )
        assert sum(isinstance(item, str) for item in outcomes) == 1
        rejected = next(item for item in outcomes if isinstance(item, Exception))
        assert isinstance(rejected, ValueError)
        assert "capacity reached" in str(rejected)
        async with sessions() as session:
            rows = (await session.scalars(select(MonitoringService))).all()
            assert len(rows) == 1
            assert rows[0].container_id is None  # Pending intent consumes capacity.
            orchestration = RadarOrchestrationService.__new__(RadarOrchestrationService)
            orchestration.session = session
            # Retrying the accepted request does not allocate another worker.
            await orchestration._assert_topics_available(
                mqtt_topics=rows[0].mqtt_topic, container_name=rows[0].container_name
            )
            await session.rollback()
    finally:
        await engine.dispose()
        clear_tactic_settings_caches()
