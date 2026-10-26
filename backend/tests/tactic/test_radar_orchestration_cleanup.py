import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import docker
import pytest
from off_key_core.db import collection_runtime
from off_key_tactic_middleware.config.config import DockerConfig
from off_key_tactic_middleware.facades.docker import get_workload_docker_status
from off_key_tactic_middleware.services.orchestration import (
    radar as radar_module,
)
from off_key_tactic_middleware.services.orchestration import (
    radar_workloads as workload_module,
)
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.orchestration.radar_workloads import (
    RadarWorkloadManager,
)

from tests.support.docker import FakeAsyncDocker
from tests.support.form_pipeline import form_launch
from tests.support.orchestration import purge_results, scalars_result

NOT_FOUND = docker.errors.NotFound("missing")
TASK_LABELS = {"radar_model_type": "knn", "monitoring_strategy": "static_baseline"}
REMOVAL_FAILED = "Failed to remove one or more managed RADAR"


def _engine_error(message="internal transport issue"):
    return docker.errors.APIError(
        message,
        response=SimpleNamespace(status_code=500, url="http://docker", reason="err"),
    )


def _lookup(outcome):
    """Mock a Docker get/list call that returns ``outcome`` or raises it."""
    if isinstance(outcome, BaseException):
        return MagicMock(side_effect=outcome)
    if isinstance(outcome, dict):
        return MagicMock(side_effect=lambda key: _found(outcome, key))
    return MagicMock(return_value=outcome)


def _found(workloads, key):
    if key in workloads:
        return workloads[key]
    raise NOT_FOUND


def _fake_docker(*, service=None, services=None):
    fake = FakeAsyncDocker()
    fake.client.services.get = _lookup(service)
    if services is not None:
        fake.client.services.list = _lookup(services)
    return fake


def _task(minute, state):
    """A Swarm task created ``minute`` minutes in; a None state is malformed."""
    status = None if state is None else {"State": state}
    return {"CreatedAt": f"2024-01-01T00:{minute:02d}:00Z", "Status": status}


def _swarm_service(*tasks, labels=None):
    return MagicMock(
        tasks=MagicMock(return_value=list(tasks)),
        attrs={"Spec": {"Labels": labels or {}}},
    )


def _session(execute=None, *, row=None):
    session = AsyncMock()
    session.scalar.return_value = None
    session.get.return_value = row
    if isinstance(execute, list):
        session.execute = AsyncMock(side_effect=execute)
    elif execute is not None:
        session.execute = AsyncMock(return_value=execute)
    return session


def _orchestrator(monkeypatch, session, fake_docker=None):
    monkeypatch.setattr(
        radar_module, "get_async_docker", lambda: fake_docker or FakeAsyncDocker()
    )
    monkeypatch.setattr(radar_module, "controller_id", lambda: "this-deployment")
    return RadarOrchestrationService(session=session)


def _db_row(**overrides):
    return SimpleNamespace(
        **{
            "stop_requested_at": None,
            "desired_state": "running",
            "id": "svc-1",
            "container_id": "ctr-1",
            "container_name": "radar-static",
            "status": True,
            **overrides,
        }
    )


def _radar_environment(topic, model_type="pyod_iforest", *, monitoring=True):
    environment = {
        "SERVICE_ID": "service-1",
        "RADAR_SUBSCRIPTION_TOPICS": topic,
        "RADAR_MONITORING_STRATEGY": "static_baseline",
        "RADAR_MODEL_TYPE": model_type,
    }
    if monitoring:
        environment |= {
            "RADAR_MONITORING_CONFIG": json.dumps(
                {"strategy": "static_baseline", "model_type": model_type}
            ),
            "RADAR_SUBSCRIPTION_QOS": "1",
            "RADAR_MQTT_CLIENT_ID_PREFIX": "radar",
        }
    return MagicMock(return_value=environment)


def _grace_period(monkeypatch):
    monkeypatch.setattr(
        workload_module,
        "get_tactic_settings",
        lambda: SimpleNamespace(
            config=SimpleNamespace(radar_startup_grace_seconds=0.0)
        ),
    )


@pytest.fixture(autouse=True)
def collection_lock(monkeypatch):
    # Docker lifecycle tests use mock sessions; real locking has separate coverage.
    monkeypatch.setattr(radar_module, "lock_collection_configuration", AsyncMock())
    monkeypatch.setattr(radar_module, "pending_activations", AsyncMock(return_value=[]))
    monkeypatch.setattr(radar_module, "lock_execution_records", AsyncMock())


@pytest.fixture
def selected_collection(monkeypatch, request):
    stream = SimpleNamespace(
        accepted_topic=getattr(request, "param", "telemetry/charger-1/sine"),
        value_type="number",
        signature=("source", "charger-1", "sine", "sample", 10),
    )
    snapshot = SimpleNamespace(
        revision=1,
        catalog=SimpleNamespace(streams=lambda **_: [stream]),
        collection={"revision": 1, "status": "applied"},
    )
    monkeypatch.setattr(radar_module, "lock_collection_configuration", AsyncMock())
    monkeypatch.setattr(
        collection_runtime, "read_collection_runtime", AsyncMock(return_value=snapshot)
    )
    return stream


@pytest.mark.asyncio
async def test_production_radar_copies_required_swarm_secret_references(monkeypatch):
    required = ("EMQX_CA_CERT", "RADAR_MQTT_API_KEY", "RADAR_CHECKPOINT_SECRET")
    secrets = [
        {
            "SecretID": f"id-{target}",
            "SecretName": f"versioned-{target}",
            "File": {"Name": target, "UID": "0", "GID": "0", "Mode": 0o444},
        }
        for target in required
    ]
    template = SimpleNamespace(
        attrs={"Spec": {"TaskTemplate": {"ContainerSpec": {"Secrets": secrets}}}}
    )
    fake_docker = _fake_docker(service=template)
    fake_docker.client.services.create = MagicMock(
        return_value=SimpleNamespace(id="svc-1")
    )
    docker_defaults = DockerConfig(
        default_network="off-key_emqx-network",
        additional_networks=[],
        default_restart_policy="on-failure",
        default_restart_max_attempts=3,
        default_cpu_limit="0.5",
        default_memory_limit="512m",
        default_constraints=[],
    )
    monkeypatch.setattr(
        workload_module,
        "get_tactic_settings",
        lambda: SimpleNamespace(
            TACTIC_RADAR_SECRET_SERVICE="off-key_mqtt-radar",
            config=SimpleNamespace(docker=docker_defaults, radar_image="radar:test"),
        ),
    )
    monkeypatch.setattr(workload_module, "build_radar_workload_labels", lambda **_: {})

    workloads = RadarWorkloadManager(fake_docker)
    await workloads.create("svc-1", {"ENVIRONMENT": "production"})

    fake_docker.client.services.get.assert_called_once_with("off-key_mqtt-radar")
    mounted = fake_docker.client.services.create.call_args.kwargs["secrets"]
    assert {secret["File"]["Name"] for secret in mounted} == set(required)
    resources = fake_docker.client.services.create.call_args.kwargs["resources"]
    assert resources["Limits"] == {"NanoCPUs": 500_000_000, "MemoryBytes": 536_870_912}
    assert resources["Reservations"] == resources["Limits"]


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_removes_workloads_and_clears_db(
    monkeypatch,
):
    first = MagicMock(id="svc-1")
    second = MagicMock(id="svc-2")
    fake_docker = _fake_docker(
        services=[first, second], service={"svc-1": first, "svc-2": second}
    )
    session = _session(purge_results(scalars_result(all=["svc-1"])))

    summary = await _orchestrator(
        monkeypatch, session, fake_docker
    ).teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 2
    assert summary["docker_workloads_removed"] == 2
    assert summary["db_rows_deleted"] == 1
    # Another stack's workers on the same cluster, such as the demo's, stay.
    labels = fake_docker.client.services.list.call_args.kwargs["filters"]["label"]
    assert "radar_controller_id=this-deployment" in labels
    statements = [call.args[0] for call in session.execute.await_args_list]
    assert "WHERE services.container_id IN" in str(statements[0])
    assert "UPDATE monitoring_pipeline_runs" in str(statements[1])
    assert "DELETE FROM mqtt_topics" in str(statements[2])
    assert "DELETE FROM services" in str(statements[3])
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_raises_on_remove_failure(
    monkeypatch,
):
    broken_workload = MagicMock(id="svc-1")
    broken_workload.remove.side_effect = RuntimeError("boom")
    fake_docker = _fake_docker(services=[broken_workload], service=broken_workload)
    session = _session()

    with pytest.raises(RuntimeError, match=REMOVAL_FAILED):
        await _orchestrator(
            monkeypatch, session, fake_docker
        ).teardown_managed_radar_workloads()

    session.execute.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_cleans_up_successes_on_partial_failure(
    monkeypatch,
):
    ok_workload = MagicMock(id="svc-ok")
    broken_workload = MagicMock(id="svc-broken")
    broken_workload.remove.side_effect = RuntimeError("boom")
    fake_docker = _fake_docker(
        services=[ok_workload, broken_workload],
        service={"svc-ok": ok_workload, "svc-broken": broken_workload},
    )
    session = _session(purge_results(scalars_result(all=["svc-ok"])))

    with pytest.raises(RuntimeError, match=REMOVAL_FAILED):
        await _orchestrator(
            monkeypatch, session, fake_docker
        ).teardown_managed_radar_workloads()

    delete_stmt = session.execute.await_args_list[0].args[0]
    assert "WHERE services.container_id IN" in str(delete_stmt)
    assert delete_stmt.compile().params == {"container_id_1": ["svc-ok"]}
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "expected"),
    [
        pytest.param(RuntimeError("boom"), "error", id="service-lookup-fails"),
        pytest.param(
            _swarm_service(_task(0, "failed"), _task(1, "running")),
            "running",
            id="latest-task-state",
        ),
        pytest.param(
            _swarm_service(_task(0, None)), "unknown", id="non-mapping-status"
        ),
        pytest.param(
            _swarm_service(None, _task(0, "running")),
            "running",
            id="malformed-task-ignored",
        ),
        pytest.param(_swarm_service(), "no_tasks", id="no-tasks"),
    ],
)
async def test_workload_status(service, expected):
    fake_docker = _fake_docker(service=service)

    assert await get_workload_docker_status(fake_docker, "ctr-1") == expected


@pytest.mark.asyncio
async def test_workload_status_reports_missing_and_unidentified_workloads():
    fake_docker = _fake_docker(service=NOT_FOUND)

    assert await get_workload_docker_status(fake_docker, "ctr-1") == "not_found"
    assert await get_workload_docker_status(fake_docker, "") == "no_container_id"


@pytest.mark.asyncio
async def test_startup_validation_tolerates_non_mapping_task_status(monkeypatch):
    fake_docker = _fake_docker(service=_swarm_service(_task(0, None), _task(1, None)))
    _grace_period(monkeypatch)

    workloads = RadarWorkloadManager(fake_docker)
    await workloads.validate_started(SimpleNamespace(id="ctr-1"))


@pytest.mark.asyncio
async def test_startup_validation_raises_with_the_failed_task_error(monkeypatch):
    failed = _task(0, "failed")
    failed["Status"]["Err"] = "missing dependency"
    fake_docker = _fake_docker(service=_swarm_service(failed))
    _grace_period(monkeypatch)
    service = _orchestrator(monkeypatch, _session(), fake_docker)

    with pytest.raises(RuntimeError, match=r"task_state=failed.*missing dependency"):
        await service.workloads.validate_started(SimpleNamespace(id="ctr-1"))


@pytest.mark.asyncio
async def test_startup_validation_raises_when_the_service_disappears(monkeypatch):
    fake_docker = _fake_docker(service=NOT_FOUND)
    _grace_period(monkeypatch)

    with pytest.raises(RuntimeError, match="disappeared during startup"):
        await RadarWorkloadManager(fake_docker).validate_started(
            SimpleNamespace(id="ctr-1")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service", "expected"),
    [
        pytest.param(
            _swarm_service(_task(0, "running"), _task(1, "exited"), labels=TASK_LABELS),
            ("exited", TASK_LABELS),
            id="latest-service-task",
        ),
        pytest.param(
            _swarm_service(labels=TASK_LABELS),
            ("no_tasks", TASK_LABELS),
            id="service-without-tasks",
        ),
        pytest.param(_engine_error(), ("error", {}), id="non-swarm-api-error"),
    ],
)
async def test_get_docker_status_and_labels_reads_the_service(service, expected):
    fake_docker = _fake_docker(service=service)

    workloads = RadarWorkloadManager(fake_docker)

    assert await workloads.get_status_and_labels("ctr-1") == expected
    fake_docker.client.services.get.assert_called_once_with("ctr-1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs", "workload_present"),
    [
        pytest.param("stop", {"container_name": "radar-static"}, True, id="stop-name"),
        pytest.param(
            "stop", {"container_name": "radar-static"}, False, id="stop-name-missing"
        ),
        pytest.param("stop", {"container_id": "ctr-1"}, True, id="stop-id"),
        pytest.param("delete", {"service_id": "svc-1"}, True, id="delete"),
    ],
)
async def test_removal_deletes_db_row_after_removing_workload(
    monkeypatch, operation, kwargs, workload_present
):
    db_row = _db_row()
    workload = MagicMock(id="ctr-1")
    fake_docker = _fake_docker(service=workload if workload_present else NOT_FOUND)
    session = _session(purge_results(scalars_result(first=db_row)), row=db_row)
    service = _orchestrator(monkeypatch, session, fake_docker)

    if operation == "stop":
        assert await service.stop_radar_service(**kwargs) is True
    else:
        assert await service.delete_radar_service(**kwargs) is True

    if workload_present:
        workload.scale.assert_called_once_with(0)
        workload.remove.assert_called_once_with()
    assert session.execute.await_count == 4
    assert session.commit.await_count == 2
    assert db_row.desired_state == "deleted"
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        ("stop", {"container_name": "missing"}),
        ("stop", {"container_id": "missing"}),
        ("delete", {"service_id": "missing"}),
    ],
)
async def test_removal_returns_false_when_service_not_found(
    monkeypatch, operation, kwargs
):
    fake_docker = _fake_docker(service=MagicMock())
    session = _session(scalars_result(first=None))
    service = _orchestrator(monkeypatch, session, fake_docker)

    if operation == "stop":
        assert await service.stop_radar_service(**kwargs) is False
    else:
        assert await service.delete_radar_service(**kwargs) is False

    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_and_get_require_exactly_one_identifier(monkeypatch):
    session = _session()
    service = _orchestrator(monkeypatch, session)

    assert await service.stop_radar_service() is False
    assert (
        await service.stop_radar_service(container_name="radar-a", container_id="ctr-a")
        is False
    )
    assert await service.get_radar_service() is None
    assert (
        await service.get_radar_service(container_name="radar-a", container_id="ctr-a")
        is None
    )
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "labels", "model_type"),
    [
        ({"container_id": "ctr-1"}, TASK_LABELS, "knn"),
        (
            {"container_name": "radar-static"},
            {"monitoring_strategy": "static_baseline"},
            None,
        ),
    ],
)
async def test_get_radar_service_resolves_identifier(
    monkeypatch, kwargs, labels, model_type
):
    db_row = _db_row(
        mqtt_topic=["telemetry/a"],
        operational_status={"stage": "starting"},
        operational_stage="starting",
        operational_updated_at=None,
        created_at=None,
    )
    fake_docker = _fake_docker(
        service=_swarm_service(_task(0, "running"), labels=labels)
    )
    session = _session(scalars_result(first=db_row), row=db_row)

    detail = await _orchestrator(monkeypatch, session, fake_docker).get_radar_service(
        **kwargs
    )

    assert detail is not None
    assert detail["id"] == "svc-1"
    assert detail["container_id"] == "ctr-1"
    assert detail["container_name"] == "radar-static"
    assert detail["docker_status"] == "running"
    assert detail["monitoring_strategy"] == "static_baseline"
    assert detail["model_type"] == model_type
    assert fake_docker.client.services.get.call_count >= 1


@pytest.mark.asyncio
async def test_delete_radar_service_leaves_db_row_when_workload_remove_fails(
    monkeypatch,
):
    db_row = _db_row()
    workload = MagicMock(id="ctr-1")
    workload.remove.side_effect = RuntimeError("boom")
    fake_docker = _fake_docker(service=workload)
    session = _session(scalars_result(first=db_row), row=db_row)

    service = _orchestrator(monkeypatch, session, fake_docker)

    assert await service.delete_radar_service("svc-1") is False
    workload.remove.assert_called_once_with()
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert db_row.desired_state == "deleted"
    assert db_row.stop_requested_at is not None
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [True, False])
async def test_find_workload_resolves_the_durable_service_name(present):
    service = MagicMock(id="svc-1")
    fake_docker = _fake_docker(service=service if present else NOT_FOUND)

    result = await RadarWorkloadManager(fake_docker).find("x")

    assert result is (service if present else None)
    fake_docker.client.services.get.assert_called_once_with("radar-x")


@pytest.mark.asyncio
async def test_find_workload_raises_for_non_swarm_api_error():
    fake_docker = _fake_docker(service=_engine_error("internal server error"))

    with pytest.raises(docker.errors.APIError):
        await RadarWorkloadManager(fake_docker).find("x")


@pytest.mark.asyncio
async def test_remove_workload_for_delete_returns_false_when_missing():
    fake_docker = _fake_docker(service=NOT_FOUND)

    assert await RadarWorkloadManager(fake_docker).remove("ctr-missing") is False
    fake_docker.client.services.get.assert_called_once_with("ctr-missing")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected_collection",
    [
        "telemetry/charger-1/sine",
        f"telemetry/entity-{'a' * 64}/reading-{'b' * 64}",
    ],
    indirect=True,
)
async def test_create_radar_service_never_launches_before_intent_commit(
    monkeypatch,
    selected_collection,
):
    session = _session(scalars_result(first=None))
    session.add = MagicMock()
    session.commit.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(
        radar_module,
        "build_radar_environment",
        _radar_environment(selected_collection.accepted_topic),
    )
    service = _orchestrator(monkeypatch, session)
    service.workloads.create = AsyncMock(return_value=SimpleNamespace(id="workload-1"))
    service.workloads.validate_started = AsyncMock()

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.create_radar_service(
            form_launch(
                container_name="radar-duplicate",
                mqtt_topics=[selected_collection.accepted_topic],
                model_type="pyod_knn",
            ),
            deployment_revision="release",
        )

    session.rollback.assert_awaited_once()
    service.workloads.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_active_service_with_missing_workload_is_recreated(
    monkeypatch,
    selected_collection,
):
    db_row = _db_row(
        id="old-svc",
        container_id="missing-workload",
        container_name="radar-stale",
        mqtt_topic=["telemetry/charger-1/sine"],
        operational_status={},
        operational_stage="starting",
        operational_updated_at=None,
    )
    ownership = scalars_result()
    session = _session(
        [ownership, *purge_results(scalars_result(first=db_row)), ownership], row=db_row
    )
    session.add = MagicMock()
    monkeypatch.setattr(
        radar_module,
        "build_radar_environment",
        _radar_environment("telemetry/charger-1/sine"),
    )
    service = _orchestrator(monkeypatch, session)
    service.workloads.get_status_and_labels = AsyncMock(return_value=("not_found", {}))
    service.workloads.remove = AsyncMock(return_value=False)
    service.workloads.create = AsyncMock(
        return_value=SimpleNamespace(id="new-workload")
    )
    service.workloads.validate_started = AsyncMock()

    async def attach_pending(_controller, _service_id):
        pending = session.add.call_args.args[0]
        pending.container_id = "new-workload"
        return pending

    monkeypatch.setattr(
        radar_module.RadarLifecycleController, "complete_creation", attach_pending
    )

    created = await service.create_radar_service(
        form_launch(
            container_name="radar-stale",
            mqtt_topics=["telemetry/charger-1/sine"],
            model_type="pyod_iforest",
        ),
        deployment_revision="release",
    )

    assert created.container_name == "radar-stale"
    assert created.container_id == "new-workload"
    assert session.commit.await_count == 4
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_existing_active_service_rejects_config_fingerprint_mismatch(
    monkeypatch,
    selected_collection,
):
    db_row = _db_row(
        id="svc-existing",
        container_id="workload-1",
        container_name="radar-existing",
        mqtt_topic=["telemetry/charger-1/sine"],
    )
    session = _session(scalars_result(first=db_row), row=db_row)
    monkeypatch.setattr(
        radar_module,
        "build_radar_environment",
        _radar_environment("telemetry/charger-1/sine", "knn", monitoring=False),
    )
    service = _orchestrator(monkeypatch, session)
    service.workloads.get_status_and_labels = AsyncMock(
        return_value=("running", {"radar_config_fingerprint": "different"})
    )

    with pytest.raises(ValueError, match="different RADAR configuration"):
        await service.create_radar_service(
            form_launch(
                container_name="radar-existing",
                mqtt_topics=["telemetry/charger-1/sine"],
                model_type="pyod_knn",
            ),
            deployment_revision="release",
        )

    assert db_row.status is True
    session.commit.assert_awaited_once()
