"""Reject invalid resource settings and enforce fleet admission with real locks."""

import asyncio
import os
import time
from contextlib import suppress
from uuid import uuid4

import docker
import pytest
from docker.types import Resources
from off_key_core.config.resource_budget import (
    MEBIBYTE,
    RadarResourceBudget,
    parse_cpu_nanos,
    parse_memory_bytes,
)
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_tactic_middleware.config.config import (
    DockerConfig,
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

pytestmark = pytest.mark.radar_integration


@pytest.mark.parametrize(
    "value", ["", "0", "0m", "-1m", "NaN", "inf", "bad", "1ib", "0.1b"]
)
def test_invalid_memory_limits_fail_validation_without_fallback(value):
    with pytest.raises(ValidationError):
        DockerConfig(default_memory_limit=value)


@pytest.mark.parametrize(
    "value", ["", "0", "-1", "NaN", "Infinity", "bad", "0.0000000001", "1e999999999999"]
)
def test_invalid_cpu_limits_fail_validation_without_fallback(value):
    with pytest.raises(ValidationError):
        DockerConfig(default_cpu_limit=value)


def test_binary_memory_units_and_cpu_quantities_have_exact_meaning():
    assert parse_memory_bytes("512m") == 512 * MEBIBYTE
    assert parse_memory_bytes("0.5 GiB") == 512 * MEBIBYTE
    assert parse_memory_bytes("1024") == 1024
    assert parse_cpu_nanos("0.5") == 500_000_000
    assert parse_cpu_nanos("0.000000001") == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"default_memory_reservation": "0"},
        {"default_cpu_reservation": "0"},
        {"default_memory_reservation": "1g"},
        {"default_cpu_reservation": "1"},
    ],
)
def test_reservations_are_positive_and_cannot_exceed_limits(overrides):
    with pytest.raises(ValidationError):
        DockerConfig(**overrides)


def test_default_worker_and_scheduler_budgets_agree():
    settings = TacticSettings()
    config = settings.config
    budget = config.docker.resource_budget
    assert (
        config.radar_defaults.memory_limit_mb
        == MQTTRadarConfig().memory_limit_mb
        == 384
    )
    assert (
        budget.memory_limit_bytes == budget.memory_reservation_bytes == 512 * MEBIBYTE
    )
    assert budget.cpu_limit_nanos == budget.cpu_reservation_nanos == 500_000_000
    assert config.radar_max_active_monitors == 20
    assert (
        config.radar_defaults.max_queue_size * config.radar_defaults.max_payload_bytes
        == 16 * MEBIBYTE
    )


@pytest.mark.parametrize("target", [512, 1024])
def test_internal_target_cannot_reach_the_hard_container_limit(target):
    with pytest.raises(ValidationError, match="below its Docker hard limit"):
        TacticConfig(
            docker=DockerConfig(),
            radar_defaults=RadarDefaultsConfig(memory_limit_mb=target),
        )


@pytest.mark.parametrize("factory", [MQTTRadarConfig, RadarDefaultsConfig])
def test_queue_payload_capacity_must_fit_inside_memory_target(factory):
    with pytest.raises(ValidationError, match="queued MQTT payload bytes"):
        factory(max_queue_size=1024, max_payload_bytes=1048576)


def test_operator_capacity_and_resource_reservations_are_typed():
    settings = TacticSettings(
        TACTIC_RADAR_MAX_ACTIVE_MONITORS=4,
        TACTIC_RADAR_STOP_TIMEOUT_SECONDS=45,
        TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT="1g",
        TACTIC_DOCKER_DEFAULT_MEMORY_RESERVATION="768m",
        TACTIC_DOCKER_DEFAULT_CPU_LIMIT="1.5",
        TACTIC_DOCKER_DEFAULT_CPU_RESERVATION="1",
        TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE=128,
        TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES=32768,
    )
    config = settings.config
    assert config.radar_max_active_monitors == 4
    assert config.radar_stop_timeout_seconds == 45
    assert config.docker.resource_budget.memory_reservation_bytes == 768 * MEBIBYTE
    assert config.docker.resource_budget.cpu_reservation_nanos == 1_000_000_000
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


def test_real_swarm_scheduler_respects_cpu_reservations():
    if os.getenv("TEST_RADAR_DOCKER") != "1":
        pytest.skip("Requires explicit disposable Docker Swarm integration")
    client = docker.from_env()
    assert client.info()["Swarm"]["ControlAvailable"]
    service = None
    owner = "radar-budget-" + uuid4().hex[:12]
    try:
        largest_cpu = max(
            node.attrs["Description"]["Resources"]["NanoCPUs"]
            for node in client.nodes.list()
        )
        budget = RadarResourceBudget(
            memory_limit_bytes=512 * MEBIBYTE,
            memory_reservation_bytes=512 * MEBIBYTE,
            cpu_limit_nanos=largest_cpu + 1_000_000_000,
            cpu_reservation_nanos=largest_cpu + 1_000_000_000,
        )
        service = client.services.create(
            "eclipse-mosquitto:2.0",
            name=owner,
            command=["/bin/sh", "-c", "sleep 60"],
            labels={"off-key.integration-owner": owner},
            resources=Resources(
                cpu_limit=budget.cpu_limit_nanos,
                mem_limit=budget.memory_limit_bytes,
                cpu_reservation=budget.cpu_reservation_nanos,
                mem_reservation=budget.memory_reservation_bytes,
            ),
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            tasks = service.tasks()
            if tasks and "insufficient resources" in tasks[-1].get("Status", {}).get(
                "Err", ""
            ):
                assert not tasks[-1].get("NodeID")
                break
            time.sleep(0.1)
        else:
            pytest.fail("Swarm did not retain an oversized CPU reservation as pending")
        service.reload()
        resources = service.attrs["Spec"]["TaskTemplate"]["Resources"]
        assert resources["Reservations"]["NanoCPUs"] == budget.cpu_reservation_nanos
        assert (
            resources["Reservations"]["MemoryBytes"] == budget.memory_reservation_bytes
        )
    finally:
        if service is not None:
            service.reload()
            assert service.attrs["Spec"]["Labels"]["off-key.integration-owner"] == owner
            with suppress(docker.errors.NotFound):
                service.remove()
        client.close()
