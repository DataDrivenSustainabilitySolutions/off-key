import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db import collection_runtime
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
    Workload,
)

from tests.support.form_pipeline import form_launch
from tests.support.orchestration import purge_results, scalars_result

TASK_LABELS = {"radar_model_type": "knn", "monitoring_strategy": "static_baseline"}
REMOVAL_FAILED = "Failed to remove one or more managed RADAR"


class MemoryWorkloads(RadarWorkloadManager):
    """The manager's orchestration surface over an in-memory table."""

    def __init__(self, *workloads, failing=()):
        super().__init__(sessions=None)
        self.rows = {workload.id: workload for workload in workloads}
        self.failing = set(failing)
        self.removed = []

    async def get(self, workload_id):
        return self.rows.get(workload_id) if workload_id else None

    async def find_named(self, name):
        return next((w for w in self.rows.values() if w.name == name), None)

    async def list_managed(self):
        return [w for w in self.rows.values() if w.kind == "monitor"]

    async def statuses_and_labels(self, workload_ids):
        found = []
        for workload_id in workload_ids:
            workload = self.rows.get(workload_id) if workload_id else None
            if not workload_id:
                found.append(("no_container_id", {}))
            elif workload is None:
                found.append(("not_found", {}))
            else:
                found.append((workload.state, workload.labels))
        return found

    async def remove(self, workload_id):
        if workload_id in self.failing:
            raise RuntimeError("RADAR workload has not stopped")
        if self.rows.pop(workload_id or "", None) is None:
            return False
        self.removed.append(workload_id)
        return True


def monitor(workload_id, *, state="running", labels=None):
    return Workload(
        id=workload_id,
        name=f"radar-{workload_id}",
        kind="monitor",
        runtime="radar:test",
        labels=labels or {},
        state=state,
    )


def _session(execute=None, *, row=None):
    session = AsyncMock()
    # AsyncSession.add_all is synchronous; an AsyncMock would leave a coroutine.
    session.add_all = MagicMock()
    session.scalar.return_value = None
    session.get.return_value = row
    if isinstance(execute, list):
        session.execute = AsyncMock(side_effect=execute)
    elif execute is not None:
        session.execute = AsyncMock(return_value=execute)
    return session


def _orchestrator(monkeypatch, session, workloads=None):
    return RadarOrchestrationService(
        session=session, workloads=workloads or MemoryWorkloads()
    )


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
    # Lifecycle tests use mock sessions; real locking has separate coverage.
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
async def test_teardown_managed_radar_workloads_removes_workloads_and_clears_db(
    monkeypatch,
):
    workloads = MemoryWorkloads(monitor("svc-1"), monitor("svc-2"))
    session = _session(purge_results(scalars_result(all=["svc-1"])))

    summary = await _orchestrator(
        monkeypatch, session, workloads
    ).teardown_managed_radar_workloads()

    assert summary["workloads_targeted"] == 2
    assert summary["workloads_removed"] == 2
    assert summary["db_rows_deleted"] == 1
    assert sorted(workloads.removed) == ["svc-1", "svc-2"]
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
    workloads = MemoryWorkloads(monitor("svc-1"), failing={"svc-1"})
    session = _session()

    with pytest.raises(RuntimeError, match=REMOVAL_FAILED):
        await _orchestrator(
            monkeypatch, session, workloads
        ).teardown_managed_radar_workloads()

    session.execute.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_teardown_managed_radar_workloads_cleans_up_successes_on_partial_failure(
    monkeypatch,
):
    workloads = MemoryWorkloads(
        monitor("svc-ok"), monitor("svc-broken"), failing={"svc-broken"}
    )
    session = _session(purge_results(scalars_result(all=["svc-ok"])))

    with pytest.raises(RuntimeError, match=REMOVAL_FAILED):
        await _orchestrator(
            monkeypatch, session, workloads
        ).teardown_managed_radar_workloads()

    delete_stmt = session.execute.await_args_list[0].args[0]
    assert "WHERE services.container_id IN" in str(delete_stmt)
    assert delete_stmt.compile().params == {"container_id_1": ["svc-ok"]}
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "running"])
async def test_startup_validation_accepts_a_workload_that_waits_or_runs(
    monkeypatch, state
):
    _grace_period(monkeypatch)
    workloads = MemoryWorkloads(monitor("ctr-1", state=state))
    await workloads.validate_started(SimpleNamespace(id="ctr-1"))


@pytest.mark.asyncio
async def test_startup_validation_raises_with_the_reason_it_ended(monkeypatch):
    _grace_period(monkeypatch)
    ended = replace(monitor("ctr-1", state="failed"), detail="missing dependency")
    workloads = MemoryWorkloads(ended)

    with pytest.raises(RuntimeError, match=r"state=failed.*missing dependency"):
        await workloads.validate_started(SimpleNamespace(id="ctr-1"))


@pytest.mark.asyncio
async def test_startup_validation_raises_when_the_workload_disappears(monkeypatch):
    _grace_period(monkeypatch)

    with pytest.raises(RuntimeError, match="disappeared during startup"):
        await MemoryWorkloads().validate_started(SimpleNamespace(id="ctr-1"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs", "workload_present"),
    [
        pytest.param("stop", {"service_id": "svc-1"}, True, id="stop"),
        pytest.param("stop", {"service_id": "svc-1"}, False, id="stop-missing"),
        pytest.param("delete", {"service_id": "svc-1"}, True, id="delete"),
    ],
)
async def test_removal_deletes_db_row_after_removing_workload(
    monkeypatch, operation, kwargs, workload_present
):
    db_row = _db_row()
    workloads = MemoryWorkloads(*([monitor("ctr-1")] if workload_present else []))
    session = _session(purge_results(scalars_result(first=db_row)), row=db_row)
    service = _orchestrator(monkeypatch, session, workloads)

    if operation == "stop":
        assert await service.stop_radar_service(**kwargs) is True
    else:
        assert await service.delete_radar_service(**kwargs) is True

    assert workloads.removed == (["ctr-1"] if workload_present else [])
    assert session.execute.await_count == 4
    assert session.commit.await_count == 2
    assert db_row.desired_state == "deleted"
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "kwargs"),
    [
        ("stop", {"service_id": "missing"}),
        ("delete", {"service_id": "missing"}),
    ],
)
async def test_removal_returns_false_when_service_not_found(
    monkeypatch, operation, kwargs
):
    session = _session(scalars_result(first=None))
    service = _orchestrator(monkeypatch, session)

    if operation == "stop":
        assert await service.stop_radar_service(**kwargs) is False
    else:
        assert await service.delete_radar_service(**kwargs) is False

    session.execute.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("labels", "model_type"),
    [
        (TASK_LABELS, "knn"),
        ({"monitoring_strategy": "static_baseline"}, None),
    ],
)
async def test_get_radar_service_reads_saved_configuration_over_labels(
    monkeypatch, labels, model_type
):
    db_row = _db_row(
        mqtt_topic=["telemetry/a"],
        operational_status={"stage": "starting"},
        operational_stage="starting",
        operational_updated_at=None,
        created_at=None,
    )
    workloads = MemoryWorkloads(monitor("ctr-1", labels=labels))
    session = _session(scalars_result(first=db_row), row=db_row)

    detail = await _orchestrator(monkeypatch, session, workloads).get_radar_service(
        "svc-1"
    )

    assert detail is not None
    assert detail["id"] == "svc-1"
    assert detail["container_id"] == "ctr-1"
    assert detail["container_name"] == "radar-static"
    assert detail["workload_status"] == "running"
    assert detail["monitoring_strategy"] == "static_baseline"
    assert detail["model_type"] == model_type


@pytest.mark.asyncio
async def test_delete_radar_service_leaves_db_row_when_workload_remove_fails(
    monkeypatch,
):
    db_row = _db_row()
    workloads = MemoryWorkloads(monitor("ctr-1"), failing={"ctr-1"})
    session = _session(scalars_result(first=db_row), row=db_row)

    service = _orchestrator(monkeypatch, session, workloads)

    assert await service.delete_radar_service("svc-1") is False
    assert "ctr-1" in workloads.rows
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert db_row.desired_state == "deleted"
    assert db_row.stop_requested_at is not None
    session.rollback.assert_awaited_once()


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
