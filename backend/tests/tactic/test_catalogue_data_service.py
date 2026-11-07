"""Devices, measurements and evidence are addressed by catalogue id, and the
recorded identity behind them never leaves TACTIC."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.schemas.collection_activity import reading_is_receiving
from off_key_core.schemas.devices import ChartEvidence
from off_key_core.schemas.system import SystemRuntime, SystemSnapshot
from off_key_tactic_middleware.domain import NotFoundError, ValidationError
from off_key_tactic_middleware.repositories.data import MonitoringEvidenceRepository
from off_key_tactic_middleware.services.data.catalogue_data import (
    CatalogueDataService,
)
from pydantic import ValidationError as SchemaError

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
PUMP = "entity-pump"
BROKER = "entity-broker"


def snapshot() -> SystemSnapshot:
    readings = [
        ("flow", "pump", PUMP, "key-flow"),
        ("pressure", "pump", PUMP, "key-pressure"),
        ("outside", None, BROKER, "key-outside"),
        ("spare", "idle", None, None),
    ]
    return SystemSnapshot.model_validate(
        {
            "revision": 4,
            "storage_origin": "saved",
            "document": {
                "brokers": [{"id": "broker", "label": "MQTT", "host": "localhost"}],
                "devices": [
                    {"id": "pump", "label": "Pump", "broker_id": "broker"},
                    {"id": "idle", "label": "Idle", "parent_id": "pump"},
                ],
                "readings": [
                    {
                        "id": reading,
                        "label": reading.title(),
                        "broker_id": "broker",
                        "device_id": device,
                        "topic": f"site/{reading}",
                    }
                    for reading, device, _, _ in readings
                ],
            },
            "runtime": {
                "bindings": {
                    reading: {"entity_id": entity, "telemetry_key": key}
                    for reading, _, entity, key in readings
                    if entity is not None
                }
            },
        }
    )


def service(session=None) -> CatalogueDataService:
    data = CatalogueDataService(session or AsyncMock(), snapshot())
    data._telemetry = AsyncMock()
    data._evidence = AsyncMock()
    return data


def evidence(sequence_number: int, **overrides):
    row = {
        "service_id": "monitor-1",
        "timestamp": NOW,
        "sequence_number": sequence_number,
        "charger_id": PUMP,
        "sensor_set": ["key-flow", "key-gone"],
        "input_timestamps": {"key-flow": NOW.isoformat(), "key-gone": NOW.isoformat()},
        "strategy": "static_baseline",
        "model_type": None,
        "p_value": 0.2,
        "anomaly_score": None,
        "e_value": 1.2,
        "e_value_is_infinite": False,
        "log_e_value": 0.18,
        "restarted_martingale": 4.0,
        "restarted_martingale_is_infinite": False,
        "log_restarted_martingale": 1.39,
        "tracker_results": [],
        "detector_results": None,
        "detector_inputs": None,
        "threshold": 100.0,
        "alarm": False,
        "created": NOW + timedelta(milliseconds=1),
    }
    return SimpleNamespace(**(row | overrides))


@pytest.mark.asyncio
async def test_measurements_resolve_the_reading_to_its_recorded_identity():
    data = service()

    await data.measurements("pressure", limit=10, paginated=False)
    await data.measurement_buckets("outside", start=None, end=None, buckets=60)

    data._telemetry.get_telemetry_data.assert_awaited_once_with(
        charger_id=PUMP, telemetry_type="key-pressure", limit=10, paginated=False
    )
    data._telemetry.get_telemetry_range.assert_awaited_once_with(
        charger_id=BROKER,
        telemetry_type="key-outside",
        start=None,
        end=None,
        buckets=60,
    )


@pytest.mark.asyncio
async def test_unknown_readings_and_devices_are_not_found():
    data = service()

    with pytest.raises(NotFoundError, match="Reading"):
        await data.measurements("missing", limit=10)
    with pytest.raises(NotFoundError, match="Device"):
        data.device_readings("missing")
    with pytest.raises(NotFoundError, match="Reading"):
        await data.evidence("missing", limit=10)


def test_device_readings_are_the_catalogue_readings_of_that_device():
    assert [stream.id for stream in service().device_readings("pump")] == [
        "flow",
        "pressure",
    ]
    assert [stream.id for stream in service().device_readings("idle")] == ["spare"]


@pytest.mark.asyncio
async def test_devices_report_whether_their_entity_is_sending(monkeypatch):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(charger_id=PUMP, online=True, last_seen="2026-11-06T11:59:00")
    ]
    session.execute.return_value = result
    data = service(session)
    from off_key_tactic_middleware.services.data import catalogue_data

    class Clock:
        @staticmethod
        def now(_):
            return NOW

    monkeypatch.setattr(catalogue_data, "datetime", Clock)
    data._runtime.mode = "collection"
    data._runtime.collection = {
        "revision": 0,
        "status": "applied",
        "checked_at": NOW.isoformat(),
    }
    data._runtime.ingress = {
        "revision": 0,
        "status": "applied",
        "checked_at": NOW.isoformat(),
        "sources": {"broker": {"state": "connected"}},
        "readings": {
            "flow": {"fresh_received_at": (NOW - timedelta(seconds=60)).isoformat()}
        },
    }
    data._runtime.bindings["flow"].update(
        connection_id="broker", policy={"mode": "original"}
    )

    devices = await data.devices(active=None)

    assert devices == [
        {
            "id": "pump",
            "label": "Pump",
            "kind": "device",
            "broker_id": "broker",
            "parent_id": None,
            "reading_ids": ["flow", "pressure"],
            "online": True,
            "last_seen": "2026-11-06T11:59:00",
        },
        {
            "id": "idle",
            "label": "Idle",
            "kind": "device",
            "broker_id": None,
            "parent_id": "pump",
            "reading_ids": ["spare"],
            "online": False,
            "last_seen": None,
        },
    ]
    assert [device["id"] for device in await data.devices(active=False)] == ["idle"]
    data._runtime.ingress["readings"]["flow"]["fresh_received_at"] = (
        NOW - timedelta(minutes=3)
    ).isoformat()
    assert await data.devices(active=True) == []
    assert (await data.devices(active=False))[0]["online"] is False


@pytest.mark.parametrize(
    ("age", "typical", "receiving"),
    [
        (119, None, True),
        (120, None, False),
        (500, 180, True),
        (540, 180, False),
        (1800, 86400, False),
        (-301, 1, False),
    ],
)
def test_receiving_window_is_fresh_bounded_and_requires_current_workers(
    age, typical, receiving
):
    runtime = SystemRuntime(
        mode="collection",
        collection_revision=2,
        bindings={
            "r": {"connection_id": "b", "policy": {"mode": "original"}},
        },
        collection={"status": "applied", "revision": 2, "checked_at": NOW.isoformat()},
        ingress={
            "status": "applied",
            "revision": 2,
            "checked_at": NOW.isoformat(),
            "sources": {"b": {"state": "connected"}},
            "readings": {
                "r": {
                    "fresh_received_at": (NOW - timedelta(seconds=age)).isoformat(),
                    "typical_interval_seconds": typical,
                }
            },
        },
    )
    assert reading_is_receiving(runtime, "r", NOW) is receiving
    for state in (runtime.collection, runtime.ingress):
        state["checked_at"] = (NOW - timedelta(seconds=30)).isoformat()
        assert not reading_is_receiving(runtime, "r", NOW)
        state["checked_at"] = NOW.isoformat()
        state["revision"] = 1
        assert not reading_is_receiving(runtime, "r", NOW)
        state["revision"] = 2
    runtime.ingress["sources"]["b"]["state"] = "error"
    assert not reading_is_receiving(runtime, "r", NOW)
    runtime.ingress["sources"]["b"]["state"] = "connected"
    runtime.bindings["r"]["policy"]["mode"] = "off"
    assert not reading_is_receiving(runtime, "r", NOW)


@pytest.mark.asyncio
async def test_chart_evidence_of_a_device_covers_its_readings_by_catalogue_id():
    data = service()
    data._evidence.list_chart.return_value = [evidence(2)]

    rows = await data.chart_evidence(
        device_id="pump",
        stream_ids=None,
        service_id="monitor-1",
        after_created=NOW,
        after_timestamp=NOW,
        after_service_id="monitor-0",
        after_sequence_number=1,
        limit=50,
    )

    data._evidence.list_chart.assert_awaited_once_with(
        scope={PUMP: frozenset({"key-flow", "key-pressure"})},
        service_id="monitor-1",
        after_created=NOW,
        after_timestamp=NOW,
        after_service_id="monitor-0",
        after_sequence_number=1,
        limit=50,
    )
    assert ChartEvidence.model_validate(rows[0]).model_dump() == {
        "monitor_id": "monitor-1",
        "timestamp": NOW,
        "sequence_number": 2,
        "reading_ids": ["flow"],
        "input_timestamps": {"flow": NOW},
        "strategy": "static_baseline",
        "model_type": None,
        "anomaly_score": None,
        "restarted_martingale": 4.0,
        "tracker_results": [],
        "detector_results": [],
        "detector_inputs": [],
        "threshold": 100.0,
        "alarm": False,
        "created": NOW + timedelta(milliseconds=1),
    }


@pytest.mark.asyncio
async def test_chart_evidence_of_readings_and_its_scope_rules():
    data = service()
    data._evidence.list_chart.return_value = []
    page = {
        "service_id": None,
        "after_created": None,
        "after_timestamp": None,
        "after_service_id": None,
        "after_sequence_number": None,
        "limit": 5,
    }

    await data.chart_evidence(device_id=None, stream_ids=["outside", "flow"], **page)
    assert data._evidence.list_chart.await_args.kwargs["scope"] == {
        BROKER: frozenset({"key-outside"}),
        PUMP: frozenset({"key-flow"}),
    }
    # A device whose readings do not record yet has no evidence.
    assert await data.chart_evidence(device_id="idle", stream_ids=None, **page) == []
    for scope in (
        {"device_id": None, "stream_ids": None},
        {"device_id": None, "stream_ids": []},
        {"device_id": "pump", "stream_ids": ["flow"]},
    ):
        with pytest.raises(ValidationError):
            await data.chart_evidence(**scope, **page)


@pytest.mark.asyncio
async def test_reading_evidence_is_oldest_first_with_its_device():
    data = service()
    data._evidence.list_by_scope.return_value = [evidence(2), evidence(1)]

    rows = await data.evidence("flow", limit=50)

    data._evidence.list_by_scope.assert_awaited_once_with(
        scope={PUMP: frozenset({"key-flow"})}, limit=50
    )
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[0]["device_id"] == "pump"
    assert rows[0]["reading_ids"] == ["flow"]
    assert rows[0]["monitor_id"] == "monitor-1"


def test_chart_evidence_contract_requires_exact_input_timestamps():
    payload = {
        "monitor_id": "monitor-1",
        "timestamp": NOW,
        "sequence_number": 1,
        "reading_ids": ["flow"],
        "strategy": "static_baseline",
        "threshold": 100.0,
        "alarm": False,
        "created": NOW,
    }

    with pytest.raises(SchemaError, match="input_timestamps"):
        ChartEvidence.model_validate(payload)


def repository_session():
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_forward_evidence_query_pages_in_ingestion_order():
    session = repository_session()

    await MonitoringEvidenceRepository(session).list_chart(
        scope={"charger-1": None},
        after_created=NOW,
        after_timestamp=NOW - timedelta(seconds=1),
        after_service_id="svc-static",
        after_sequence_number=1,
        limit=2000,
    )

    query = str(session.execute.await_args.args[0])
    assert "monitoring_evidence.created >" in query
    assert "ORDER BY monitoring_evidence.created ASC" in query


@pytest.mark.asyncio
async def test_forward_evidence_query_rejects_incomplete_cursor():
    with pytest.raises(ValueError, match="after_service_id"):
        await MonitoringEvidenceRepository(AsyncMock()).list_chart(
            scope={"charger-1": None},
            after_created=NOW,
            after_timestamp=NOW,
            after_service_id=None,
            after_sequence_number=1,
            limit=2000,
        )


@pytest.mark.asyncio
async def test_monitor_and_reading_filters_are_applied_before_the_page_limit():
    session = repository_session()

    await MonitoringEvidenceRepository(session).list_chart(
        scope={"charger-1": frozenset({"key-b", "key-a"})},
        service_id="chosen-monitor",
        after_created=None,
        after_timestamp=None,
        after_service_id=None,
        after_sequence_number=None,
        limit=50,
    )

    compiled = session.execute.await_args.args[0].compile()
    assert "monitoring_evidence.service_id =" in str(compiled)
    assert "?|" in str(compiled)
    values = list(compiled.params.values())
    assert "chosen-monitor" in values
    assert "charger-1" in values
    assert {"key-a", "key-b"} <= set(values)
