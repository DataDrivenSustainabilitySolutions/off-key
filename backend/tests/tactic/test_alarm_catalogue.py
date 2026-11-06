"""Alarms translate catalogue readings to recorded identities and back."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.api.v1 import alarms as gateway
from off_key_core.db.models import Anomaly
from off_key_core.schemas.alarms import AlarmCreate, AlarmQuery
from off_key_core.schemas.system import SystemDocument, SystemRuntime, SystemSnapshot
from off_key_tactic_middleware.domain import NotFoundError, ValidationError
from off_key_tactic_middleware.services.data.alarm_catalogue import (
    AlarmCatalogue,
    reading_scope,
)
from off_key_tactic_middleware.services.data.alarms import AlarmService

BINDINGS = {
    "line-temperature": {"entity_id": "line", "telemetry_key": "temperature"},
    "line-pressure": {"entity_id": "line", "telemetry_key": "pressure"},
    "hall-temperature": {"entity_id": "hall", "telemetry_key": "temperature"},
}
CATALOGUE = SystemSnapshot(
    revision=1,
    storage_origin="saved",
    document=SystemDocument(
        connections=[{"id": "broker", "label": "Plant MQTT", "host": "broker"}],
        devices=[{"id": "line", "label": "Line 1", "connection_id": "broker"}],
        streams=[
            {
                "id": "line-temperature",
                "label": "Temperature",
                "connection_id": "broker",
                "device_id": "line",
                "topic": "line/temperature",
            },
            {
                "id": "line-pressure",
                "label": "Pressure",
                "connection_id": "broker",
                "device_id": "line",
                "topic": "line/pressure",
            },
            {
                "id": "hall-temperature",
                "label": "Hall temperature",
                "connection_id": "broker",
                "topic": "hall/temperature",
            },
        ],
    ),
    runtime=SystemRuntime(bindings=BINDINGS),
)
NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)


def stored(**fields) -> Anomaly:
    return Anomaly(
        **{
            "charger_id": "line",
            "timestamp": NOW,
            "telemetry_type": "temperature",
            "service_id": "",
            "anomaly_type": "spike",
            "anomaly_value": 3.0,
            "value_type": "zscore",
            "sensor_set": None,
        }
        | fields
    )


def test_an_entity_is_whole_only_when_every_reading_is_chosen():
    scope, unknown = reading_scope(
        BINDINGS, ["line-temperature", "hall-temperature", "gone"]
    )
    assert scope.pairs == {("line", "temperature"), ("hall", "temperature")}
    assert scope.whole_entities == {"hall"}
    assert scope.entities == {"line", "hall"}
    assert unknown == ["gone"]


def test_a_device_scope_takes_every_reading_and_rejects_an_unknown_device():
    names = AlarmCatalogue(CATALOGUE)
    scope = names.device_scope("line")
    assert scope.pairs == {("line", "temperature"), ("line", "pressure")}
    assert scope.whole_entities == {"line"}
    with pytest.raises(NotFoundError):
        names.device_scope("gone")


def test_alarms_name_the_device_or_broker_and_leave_out_removed_readings():
    names = AlarmCatalogue(CATALOGUE)
    alarm = names.alarm(
        "a1",
        stored(
            telemetry_type="__multivariate__",
            sensor_set=["pressure", "gone", "temperature"],
            service_id="m1",
        ),
    )
    assert alarm.model_dump(exclude={"timestamp"}) == {
        "alarm_id": "a1",
        "device_id": "line",
        "device_label": "Line 1",
        "reading_ids": ["line-pressure", "line-temperature"],
        "reading_labels": {
            "line-pressure": "Pressure",
            "line-temperature": "Temperature",
        },
        "multivariate": True,
        "alarm_type": "spike",
        "value": 3.0,
        "value_type": "zscore",
        "monitor_id": "m1",
    }
    broker = names.alarm("a2", stored(charger_id="hall"))
    assert (broker.device_id, broker.device_label) == (None, "Plant MQTT")
    assert broker.reading_ids == ["hall-temperature"]
    removed = names.alarm("a3", stored(charger_id="removed"))
    assert (removed.device_id, removed.device_label, removed.reading_ids) == (
        None,
        None,
        [],
    )
    assert removed.monitor_id is None


def test_a_new_alarm_names_readings_of_one_device():
    names = AlarmCatalogue(CATALOGUE)
    assert names.recorded(["line-pressure", "line-temperature"]) == (
        "line",
        ["pressure", "temperature"],
    )
    with pytest.raises(ValidationError):
        names.recorded(["line-pressure", "hall-temperature"])
    with pytest.raises(NotFoundError):
        names.recorded(["gone"])


async def test_a_new_alarm_over_several_readings_is_multivariate():
    repository = AsyncMock()
    repository.add.return_value = "a1"
    service = AlarmService(AsyncMock(), repository)
    alarm = await service.create_alarm(
        AlarmCreate(
            reading_ids=["line-temperature", "line-pressure"],
            timestamp=NOW,
            alarm_type="ml_tailprob_external",
            value=0.01,
        ),
        CATALOGUE,
    )
    row = repository.add.await_args.args[0]
    assert (row.charger_id, row.telemetry_type, row.sensor_set) == (
        "line",
        "__multivariate__",
        ["temperature", "pressure"],
    )
    assert (row.service_id, row.value_type) == ("", "tail_pvalue")
    assert alarm.reading_ids == ["line-temperature", "line-pressure"]
    assert alarm.multivariate and alarm.device_id == "line"

    await service.create_alarm(
        AlarmCreate(
            reading_ids=["hall-temperature"], timestamp=NOW, alarm_type="x", value=2
        ),
        CATALOGUE,
    )
    row = repository.add.await_args.args[0]
    assert (row.charger_id, row.telemetry_type, row.sensor_set) == (
        "hall",
        "temperature",
        None,
    )
    assert row.value_type == "zscore"


async def test_gateway_forwards_the_query_as_json(monkeypatch):
    request = AsyncMock(return_value={})
    monkeypatch.setattr(gateway.tactic, "request", request)
    await gateway.query_alarms(
        AlarmQuery(reading_ids=["line-temperature"], max_p_value=0.01)
    )
    sent = request.await_args.kwargs
    assert sent["endpoint"] == "/api/v1/data/alarms/query"
    assert sent["json_data"]["reading_ids"] == ["line-temperature"]
    assert sent["json_data"]["max_p_value"] == 0.01
    assert sent["json_data"]["limit"] == 200


async def test_an_empty_or_unknown_scope_answers_without_reading_alarms():
    repository = AsyncMock()
    service = AlarmService(AsyncMock(), repository)
    for reading_ids, unknown in (([], []), (["gone"], ["gone"])):
        page = await service.query(AlarmQuery(reading_ids=reading_ids), CATALOGUE)
        assert page.items == [] and page.summary.count == 0
        assert page.unknown_reading_ids == unknown
    assert (
        await service.list_alarms(
            CATALOGUE,
            device_id=None,
            stream_ids=["gone"],
            service_id=None,
            limit=10,
        )
        == []
    )
    assert repository.mock_calls == []
    with pytest.raises(ValidationError):
        await service.list_alarms(
            CATALOGUE,
            device_id="line",
            stream_ids=["line-pressure"],
            service_id=None,
            limit=10,
        )
