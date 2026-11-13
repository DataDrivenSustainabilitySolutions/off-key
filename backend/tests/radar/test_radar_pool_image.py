"""Opt-in deployment regression: the current RADAR image's pool restores a monitor.

Build backend/Dockerfile for off-key-mqtt-radar, then set TEST_RADAR_IMAGE. The
test runs that image as a pool replica next to a disposable database and broker,
kills the monitor's child the way an out-of-memory kill would, and checks the
replica restarts it from its signed checkpoint. Only containers and networks
carrying this test's ownership label are removed.
"""

import json
import math
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.db.workloads import RadarWorkload
from off_key_core.schemas.radar import StaticBaselineConfig
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.exc import OperationalError

from tests.support.form_pipeline import form_pipeline

pytestmark = [
    pytest.mark.radar_integration,
    pytest.mark.skipif(
        not os.getenv("TEST_RADAR_IMAGE"),
        reason="Requires an explicitly built current RADAR image and Docker",
    ),
]

PASSWORD = "disposable-integration-password"
# Ends the replica's monitor child with SIGKILL, as the kernel's OOM killer does.
_KILL_MONITOR = """
import os, signal
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as source:
            arguments = source.read().split(b"\\0")
    except OSError:
        continue
    if arguments[-2:] == [b"off_key_mqtt_radar", b""]:
        os.kill(int(pid), signal.SIGKILL)
        print(pid)
"""

_CHECKPOINT_PROBE = """
import asyncio
import json
import os
import time

from off_key_mqtt_radar.config.config import get_radar_settings
from off_key_mqtt_radar.config.runtime import get_radar_checkpoint_settings
from off_key_mqtt_radar.runtime_checkpoint import RuntimeCheckpointCodec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    runtime = get_radar_checkpoint_settings()
    codec = RuntimeCheckpointCodec(
        runtime.SERVICE_ID,
        get_radar_settings().config,
        runtime.durable_checkpoint_secret_bytes,
    )
    expected = json.loads(os.environ["EXPECTED_CHECKPOINT_WATERMARKS"])
    receipts = int(os.environ["EXPECTED_CHECKPOINT_RECEIPTS"])
    engine = create_async_engine(os.environ["PROBE_DATABASE_URL"], pool_size=1)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            async with engine.connect() as connection:
                record = (
                    await connection.execute(
                        text(
                            "SELECT * FROM radar_runtime_checkpoints "
                            "WHERE service_id=:id"
                        ),
                        {"id": runtime.SERVICE_ID},
                    )
                ).mappings().one_or_none()
            if record is not None:
                snapshot = codec.decode(dict(record))
                watermarks = snapshot.observation_watermarks.get("pool-test", {})
                if (
                    snapshot.processor.received_message_count >= receipts
                    and all(
                        watermarks.get(key) == value
                        for key, value in expected.items()
                    )
                ):
                    print(json.dumps({
                        "processed_count": record["processed_count"],
                        "received_message_count": (
                            snapshot.processor.received_message_count
                        ),
                        "observation_watermarks": watermarks,
                    }), flush=True)
                    return
            await asyncio.sleep(0.2)
        raise AssertionError(
            "Checkpoint did not cover every accepted receipt and watermark"
        )
    finally:
        await engine.dispose()


asyncio.run(main())
"""


def docker(*arguments: str, check: bool = True) -> str:
    return subprocess.run(
        ["docker", *arguments], check=check, capture_output=True, text=True, timeout=120
    ).stdout.strip()


def wait_for(probe, *, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {probe.__name__}")


def published_port(container: str, port: str) -> int:
    return int(docker("port", container, port).splitlines()[0].rsplit(":", 1)[1])


@pytest.fixture
def pool_runtime():
    owner = "radar-test-" + uuid4().hex[:12]
    label = f"off-key.integration-owner={owner}"
    image = os.environ["TEST_RADAR_IMAGE"]
    engine = None
    docker("network", "create", "--label", label, owner)
    try:
        database = owner + "-db"
        docker(
            "run",
            "--detach",
            "--name",
            database,
            "--network",
            owner,
            "--label",
            label,
            "--publish",
            "127.0.0.1::5432",
            "--tmpfs",
            "/var/lib/postgresql/data:rw,size=512m",
            "--memory",
            "768m",
            "--env",
            "POSTGRES_USER=radar_test",
            "--env",
            f"POSTGRES_PASSWORD={PASSWORD}",
            "--env",
            "POSTGRES_DB=radar_test",
            os.getenv("TEST_RADAR_DATABASE_IMAGE", "timescale/timescaledb:latest-pg15"),
        )
        engine = create_engine(
            f"postgresql+psycopg2://radar_test:{PASSWORD}"
            f"@127.0.0.1:{published_port(database, '5432/tcp')}/radar_test",
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )

        def database_ready():
            # The entrypoint's temporary server can answer before the final one.
            try:
                with engine.connect() as connection:
                    return connection.scalar(text("SELECT 1")) == 1
            except OperationalError:
                return False

        wait_for(database_ready)
        with engine.begin() as connection:
            apply_migrations(connection)
        broker = owner + "-mqtt"
        docker(
            "run",
            "--detach",
            "--name",
            broker,
            "--network",
            owner,
            "--label",
            label,
            "--publish",
            "127.0.0.1::1883",
            "--memory",
            "64m",
            "eclipse-mosquitto:2.0",
            "sh",
            "-c",
            "printf 'listener 1883\\nallow_anonymous true\\n' > /tmp/test.conf; "
            "exec mosquitto -c /tmp/test.conf",
        )
        wait_for(lambda: "running" in docker("logs", broker, check=False))
        pool = owner + "-pool"
        docker(
            "run",
            "--detach",
            "--name",
            pool,
            "--network",
            owner,
            "--label",
            label,
            "--memory",
            "1g",
            "--env",
            "ENVIRONMENT=development",
            "--env",
            f"RADAR_POOL_RUNTIME={image}",
            "--env",
            "RADAR_POOL_POLL_SECONDS=0.5",
            "--env",
            "RADAR_POOL_RESTART_BACKOFF_SECONDS=0.5",
            "--env",
            "RADAR_CHECKPOINT_SECRET=disposable-pool-checkpoint-secret",
            "--env",
            "POSTGRES_USER=radar_test",
            "--env",
            f"POSTGRES_PASSWORD={PASSWORD}",
            "--env",
            f"POSTGRES_HOST={database}",
            "--env",
            "POSTGRES_PORT=5432",
            "--env",
            "POSTGRES_DB=radar_test",
            image,
            "/app/bin/python",
            "-m",
            "off_key_mqtt_radar.pool",
        )
        yield owner, label, image, engine, database, broker, pool
    finally:
        if engine:
            engine.dispose()
        owned = docker("ps", "--all", "--quiet", "--filter", f"label={label}")
        for container in owned.split():
            docker("rm", "--force", container, check=False)
        docker("network", "rm", owner, check=False)


def test_current_image_pool_restores_a_killed_monitor(pool_runtime):
    owner, label, image, engine, database, broker, pool = pool_runtime
    broker_port = published_port(broker, "1883/tcp")
    service_id = owner + "-monitor"
    topics = ["telemetry/pool-test/a", "telemetry/pool-test/b"]
    with engine.begin() as connection:
        connection.execute(
            insert(MonitoringService).values(
                id=service_id,
                container_name="radar-" + service_id,
                mqtt_topic=topics,
                status=True,
                desired_state="running",
                lifecycle_version=1,
            )
        )
    monitoring = StaticBaselineConfig(
        model_params={"n_estimators": 8},
        training_window_size=20,
        calibration_window_size=8,
    )
    environment = {
        "ENVIRONMENT": "development",
        "SERVICE_ID": service_id,
        "RADAR_LIFECYCLE_VERSION": "1",
        "RADAR_MQTT_BROKER_HOST": broker,
        "RADAR_SUBSCRIPTION_TOPICS": ",".join(topics),
        "RADAR_SUBSCRIPTION_QOS": "1",
        "RADAR_PIPELINE_CONFIG": form_pipeline(monitoring, topics).model_dump_json(),
        "RADAR_CHECKPOINT_INTERVAL": "5",
        "RADAR_HEALTH_CHECK_INTERVAL": "0.5",
        "RADAR_SENSOR_FRESHNESS_SECONDS": "3",
        # Retained inputs must be rejected by their restored watermarks rather
        # than merely ageing out while the replacement process imports models.
        "RADAR_OBSERVATION_MAX_AGE_SECONDS": "600",
        "RADAR_DB_BATCH_TIMEOUT": "0.2",
        "RADAR_RATE_LIMIT_PER_MINUTE": "0",
        "RADAR_MEMORY_LIMIT_MB": "384",
    }
    workload_id = uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(
            insert(RadarWorkload).values(
                id=workload_id,
                name="radar-" + service_id,
                kind="monitor",
                labels={"radar_service_id": service_id},
                runtime=image,
                module="off_key_mqtt_radar",
                environment=environment,
                memory_limit_bytes=512 * 1024 * 1024,
                restart=True,
            )
        )

    def workload():
        with engine.connect() as connection:
            return connection.execute(
                select(RadarWorkload.__table__).where(RadarWorkload.id == workload_id)
            ).one()

    def status():
        with engine.connect() as connection:
            return (
                connection.scalar(
                    text("SELECT operational_status FROM services WHERE id=:id"),
                    {"id": service_id},
                )
                or {}
            )

    def checkpoint_count():
        with engine.connect() as connection:
            return (
                connection.scalar(
                    text(
                        "SELECT processed_count FROM radar_runtime_checkpoints "
                        "WHERE service_id=:id"
                    ),
                    {"id": service_id},
                )
                or 0
            )

    def evidence_count():
        with engine.connect() as connection:
            return connection.scalar(
                text("SELECT count(*) FROM monitoring_evidence WHERE service_id=:id"),
                {"id": service_id},
            )

    publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    publisher.connect("127.0.0.1", broker_port)
    publisher.loop_start()
    try:
        wait_for(lambda: status().get("updated_at"), timeout=120)
        index = 0
        latest_watermarks = {}
        learning_deadline = time.monotonic() + 120
        while index < 65 or not evidence_count():
            assert time.monotonic() < learning_deadline, (
                "Real worker did not produce scoring evidence within 120 seconds"
            )
            for sensor, topic in enumerate(topics):
                payload = {
                    "value": math.sin(index / 3) + sensor,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                publisher.publish(
                    topic, json.dumps(payload), qos=1, retain=True
                ).wait_for_publish(5)
                latest_watermarks[topic.rsplit("/", 1)[-1]] = datetime.fromisoformat(
                    payload["timestamp"]
                ).timestamp()
            time.sleep(0.08)
            index += 1
        # Cross-topic delivery may coalesce readings under strict-barrier
        # alignment. Drain actual receipts and verify the signed runtime state
        # contains the latest retained observation from every stream.
        drained = wait_for(
            lambda: status() if status().get("message_count", 0) >= index * 2 else None
        )
        probe_environment = environment | {
            "RADAR_CHECKPOINT_SECRET": "disposable-pool-checkpoint-secret",
            "PROBE_DATABASE_URL": "postgresql+asyncpg://radar_test:"
            f"{PASSWORD}@{database}:5432/radar_test",
            "EXPECTED_CHECKPOINT_RECEIPTS": str(drained["message_count"]),
            "EXPECTED_CHECKPOINT_WATERMARKS": json.dumps(latest_watermarks),
        }
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                owner,
                "--label",
                label,
                "--memory",
                "512m",
                *(f"--env={key}={value}" for key, value in probe_environment.items()),
                image,
                "/app/bin/python",
                "-c",
                _CHECKPOINT_PROBE,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        probe_logs = result.stdout + result.stderr
        assert result.returncode == 0, probe_logs
        verified_checkpoint = json.loads(probe_logs.splitlines()[-1])
        before = verified_checkpoint["processed_count"]
        wait_for(lambda: status().get("processed_message_count") == before)
        assert checkpoint_count() == before
        before_evidence = evidence_count()
        assert before_evidence > 0
        # The replica, running this image, claimed the row.
        assert workload().state == "running"
        killed = docker("exec", pool, "/app/bin/python", "-c", _KILL_MONITOR)
        assert killed, "The monitor's child was not found in the replica"
        restarted = wait_for(
            lambda: (
                (row := workload()).state == "running" and row.attempts == 2 and row
            ),
            timeout=120,
        )
        (crash,) = restarted.crashes
        assert crash["exit_code"] == 137
        assert "memory limit" in crash["hint"]
        wait_for(lambda: status().get("recovery", {}).get("restored"), timeout=120)
        assert status()["processed_message_count"] >= before
        assert status()["recovery"]["restored_processed_count"] >= before
        assert status()["coverage"]["has_gaps"]
        assert status()["coverage"]["possible_gap_count"] >= 1
        wait_for(
            lambda: (
                status()["coverage"]["dropped_by_reason"].get(
                    "observation_duplicate", 0
                )
                >= 2
            )
        )
        assert checkpoint_count() == before
        assert evidence_count() == before_evidence
        assert status()["coverage"]["last_gap_reason"] in {
            "worker_restart",
            "observation_duplicate",
        }
        replaced_at = datetime.now(UTC)
        for index in range(10):
            for topic in topics:
                publisher.publish(
                    topic,
                    json.dumps(
                        {
                            "value": float(index),
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    ),
                    qos=1,
                    retain=True,
                ).wait_for_publish(5)
            time.sleep(0.1)
        wait_for(lambda: checkpoint_count() > before)
        wait_for(lambda: evidence_count() > before_evidence)
        recovered = wait_for(
            lambda: (
                status()
                if status().get("activity", {}).get("last_inference_at")
                else None
            )
        )
        inferred_at = datetime.fromisoformat(recovered["activity"]["last_inference_at"])
        assert inferred_at >= replaced_at
        print(
            json.dumps(
                {
                    "image": image,
                    "attempts": workload().attempts,
                    "saved_count_before_failure": before,
                    "checkpoint_receipts_before_failure": verified_checkpoint[
                        "received_message_count"
                    ],
                    "checkpoint_watermarks_before_failure": verified_checkpoint[
                        "observation_watermarks"
                    ],
                    "checkpoint_count_after_recovery": checkpoint_count(),
                    "evidence_before_failure": before_evidence,
                    "evidence_after_recovery": evidence_count(),
                    "restored": recovered["recovery"]["restored"],
                    "coverage_gap": recovered["coverage"]["has_gaps"],
                    "replayed_observations_rejected": recovered["coverage"][
                        "dropped_by_reason"
                    ].get("observation_duplicate", 0),
                }
            )
        )
    except BaseException:
        # Current source logs are essential evidence if the deployment fails.
        print(docker("logs", "--tail", "30", database, check=False))
        print(
            json.dumps(
                {
                    "workload": str(workload()._asdict()),
                    "runtime_status": status(),
                    "checkpoint_count": checkpoint_count(),
                    "evidence_count": evidence_count(),
                },
                default=str,
            )
        )
        print(docker("logs", "--tail", "200", pool, check=False))
        raise
    finally:
        publisher.disconnect()
        publisher.loop_stop()
