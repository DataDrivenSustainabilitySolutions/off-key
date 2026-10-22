"""Opt-in deployment regressions using the current RADAR image and real Swarm.

Build backend/Dockerfile for off-key-mqtt-radar, then set TEST_RADAR_SWARM_IMAGE.
Only uniquely named resources carrying this test's ownership label are removed.
"""

import json
import math
import os
import time
from contextlib import suppress
from datetime import UTC, datetime
from uuid import uuid4

import docker
import paho.mqtt.client as mqtt
import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import StaticBaselineConfig
from sqlalchemy import create_engine, insert, text
from sqlalchemy.exc import OperationalError

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_RADAR_SWARM_IMAGE"),
    reason="Requires an explicitly built current RADAR image and local Swarm",
)

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
    engine = create_async_engine(os.environ["RADAR_DATABASE_URL"], pool_size=1)
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
                watermarks = snapshot.observation_watermarks.get("swarm-test", {})
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


def wait_for(probe, *, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = probe()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {probe.__name__}")


@pytest.fixture
def swarm_runtime():
    client = docker.from_env(timeout=15)
    assert client.info()["Swarm"]["LocalNodeState"] == "active"
    owner = "radar-test-" + uuid4().hex[:12]
    labels = {"off-key.integration-owner": owner}
    resources = []
    engine = None
    network = client.networks.create(
        owner, driver="overlay", attachable=True, labels=labels
    )
    try:
        database = client.containers.run(
            os.getenv("TEST_RADAR_DATABASE_IMAGE", "timescale/timescaledb:latest-pg15"),
            name=owner + "-db",
            network=network.name,
            environment={
                "POSTGRES_USER": "radar_test",
                "POSTGRES_PASSWORD": "disposable-integration-password",
                "POSTGRES_DB": "radar_test",
            },
            ports={"5432/tcp": ("127.0.0.1", None)},
            tmpfs={"/var/lib/postgresql/data": "rw,size=512m"},
            mem_limit="768m",
            labels=labels,
            detach=True,
        )
        resources.append(database)
        database.reload()
        database_port = database.attrs["NetworkSettings"]["Ports"]["5432/tcp"][0][
            "HostPort"
        ]
        wait_for(
            lambda: database.exec_run(["pg_isready", "-U", "radar_test"]).exit_code == 0
        )
        engine = create_engine(
            "postgresql+psycopg2://radar_test:disposable-integration-password"
            f"@127.0.0.1:{database_port}/radar_test",
            pool_pre_ping=True,
            connect_args={"connect_timeout": 5},
        )

        def database_ready():
            # pg_isready can observe the entrypoint's temporary Unix-socket
            # server before the final server accepts published TCP connections.
            try:
                with engine.connect() as connection:
                    return connection.scalar(text("SELECT 1")) == 1
            except OperationalError:
                return False

        wait_for(database_ready)
        with engine.begin() as connection:
            apply_migrations(connection)
        broker = client.containers.run(
            "eclipse-mosquitto:2.0",
            name=owner + "-mqtt",
            network=network.name,
            command=[
                "sh",
                "-c",
                "printf 'listener 1883\nallow_anonymous true\n' > /tmp/test.conf; "
                "exec mosquitto -c /tmp/test.conf",
            ],
            ports={"1883/tcp": ("127.0.0.1", None)},
            mem_limit="64m",
            labels=labels,
            detach=True,
        )
        resources.append(broker)
        broker.reload()
        broker_port = int(
            broker.attrs["NetworkSettings"]["Ports"]["1883/tcp"][0]["HostPort"]
        )
        wait_for(lambda: b"running" in broker.logs())
        yield (
            client,
            owner,
            labels,
            network,
            engine,
            database,
            broker,
            broker_port,
            resources,
        )
    finally:
        if engine:
            engine.dispose()
        for resource in reversed(resources):
            # Tests never remove unlabelled or unrelated application workloads.
            with suppress(docker.errors.NotFound):
                resource.reload()
                actual = resource.attrs.get("Spec", {}).get(
                    "Labels", resource.attrs.get("Config", {}).get("Labels", {})
                )
                assert actual.get("off-key.integration-owner") == owner
                if isinstance(resource, docker.models.services.Service):
                    resource.remove()
                else:
                    resource.remove(force=True)

        # Task containers are created by Swarm after the service itself, so they
        # are not in resources. Remove only this fixture's labelled remnants.
        def remove_owned_tasks():
            owned = client.containers.list(
                all=True, filters={"label": f"off-key.integration-owner={owner}"}
            )
            for container in owned:
                # Swarm may already be removing a task container. Its next
                # inspection must disappear before cleanup can succeed.
                with suppress(docker.errors.APIError):
                    container.remove(force=True)
            return not owned

        wait_for(remove_owned_tasks)

        def remove_network():
            try:
                network.remove()
                return True
            except docker.errors.APIError:
                return False

        wait_for(remove_network)
        client.close()


def test_current_image_restores_in_replacement_swarm_task(swarm_runtime):
    client, owner, labels, network, engine, database, broker, broker_port, resources = (
        swarm_runtime
    )
    service_id = owner + "-monitor"
    topics = ["telemetry/swarm-test/a", "telemetry/swarm-test/b"]
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
        "RADAR_CHECKPOINT_STORAGE": "database",
        "RADAR_CHECKPOINT_SECRET": "disposable-swarm-checkpoint-secret",
        "RADAR_DATABASE_URL": "postgresql+asyncpg://radar_test:disposable-integration-password"
        f"@{database.name}:5432/radar_test",
        "RADAR_MQTT_BROKER_HOST": broker.name,
        "RADAR_SUBSCRIPTION_TOPICS": ",".join(topics),
        "RADAR_SUBSCRIPTION_QOS": "1",
        "RADAR_MONITORING_CONFIG": monitoring.model_dump_json(),
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
    expected_image_id = client.images.get(os.environ["TEST_RADAR_SWARM_IMAGE"]).id
    worker = client.services.create(
        os.environ["TEST_RADAR_SWARM_IMAGE"],
        name=owner + "-worker",
        command=["/app/bin/python", "-m", "off_key_mqtt_radar"],
        env=environment,
        networks=[network.id],
        labels=labels,
        container_labels=labels,
        resources=docker.types.Resources(
            mem_limit=512 * 1024 * 1024, cpu_limit=500_000_000
        ),
        restart_policy=docker.types.RestartPolicy(
            condition="on-failure", delay=100_000_000
        ),
    )
    resources.append(worker)
    worker.reload()
    limits = worker.attrs["Spec"]["TaskTemplate"]["Resources"]["Limits"]
    assert limits == {"NanoCPUs": 500_000_000, "MemoryBytes": 512 * 1024 * 1024}

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
        probe = client.containers.run(
            expected_image_id,
            name=owner + "-checkpoint-probe",
            command=["/app/bin/python", "-c", _CHECKPOINT_PROBE],
            environment=environment
            | {
                "EXPECTED_CHECKPOINT_RECEIPTS": str(drained["message_count"]),
                "EXPECTED_CHECKPOINT_WATERMARKS": json.dumps(latest_watermarks),
            },
            network=network.id,
            labels=labels,
            mem_limit="512m",
            detach=True,
        )
        resources.append(probe)
        probe_result = probe.wait(timeout=120)
        probe_logs = probe.logs().decode(errors="replace")
        assert probe_result["StatusCode"] == 0, probe_logs
        verified_checkpoint = json.loads(probe_logs.splitlines()[-1])
        before = verified_checkpoint["processed_count"]
        wait_for(lambda: status().get("processed_message_count") == before)
        assert checkpoint_count() == before
        before_evidence = evidence_count()
        assert before_evidence > 0
        running = wait_for(
            lambda: next(
                (
                    task
                    for task in worker.tasks()
                    if task["Status"]["State"] == "running"
                ),
                None,
            )
        )
        old_container = running["Status"]["ContainerStatus"]["ContainerID"]
        old_task_container = client.containers.get(old_container)
        worker_image_id = old_task_container.image.id
        assert worker_image_id == expected_image_id
        old_task_container.kill()
        replacement = wait_for(
            lambda: next(
                (
                    task
                    for task in worker.tasks()
                    if task["Status"]["State"] == "running"
                    and task["ID"] != running["ID"]
                ),
                None,
            ),
            timeout=120,
        )
        replacement_image_id = client.containers.get(
            replacement["Status"]["ContainerStatus"]["ContainerID"]
        ).image.id
        assert replacement_image_id == expected_image_id
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
                    "image_id": expected_image_id,
                    "worker_image_id": worker_image_id,
                    "replacement_image_id": replacement_image_id,
                    "old_task_id": running["ID"],
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
        database.reload()
        print(json.dumps({"database_state": database.attrs["State"]}))
        print(database.logs(tail=30).decode(errors="replace"))
        print(
            json.dumps(
                {
                    "tasks": [task["Status"] for task in worker.tasks()],
                    "runtime_status": status(),
                    "checkpoint_count": checkpoint_count(),
                    "evidence_count": evidence_count(),
                }
            )
        )
        with suppress(docker.errors.APIError):
            logs = worker.logs(stdout=True, stderr=True, tail=100, follow=False)
            if not isinstance(logs, bytes):
                logs = b"".join(logs)
            print(logs.decode(errors="replace"))
        raise
    finally:
        publisher.disconnect()
        publisher.loop_stop()
