"""Reporting translates catalogue readings to recorded identities and back."""

from unittest.mock import AsyncMock

from off_key_api_gateway.api.v1 import anomalies as gateway
from off_key_core.schemas.reporting import AnomalyQuery
from off_key_core.schemas.system import SystemDocument, SystemRuntime, SystemSnapshot
from off_key_tactic_middleware.services.data.anomalies import AnomalyService
from off_key_tactic_middleware.services.data.reporting_scope import (
    CatalogueLabels,
    reading_scope,
)

BINDINGS = {
    "line-temperature": {"entity_id": "line", "telemetry_key": "temperature"},
    "line-pressure": {"entity_id": "line", "telemetry_key": "pressure"},
    "hall-temperature": {"entity_id": "hall", "telemetry_key": "temperature"},
}


def test_an_entity_is_whole_only_when_every_reading_is_chosen():
    scope, unknown = reading_scope(
        BINDINGS, ["line-temperature", "hall-temperature", "gone"]
    )
    assert scope.pairs == {("line", "temperature"), ("hall", "temperature")}
    assert scope.whole_entities == {"hall"}
    assert scope.entities == {"line", "hall"}
    assert unknown == ["gone"]


def test_labels_prefer_the_device_and_fall_back_to_recorded_names():
    document = SystemDocument(
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
                "id": "hall-temperature",
                "label": "Hall temperature",
                "connection_id": "broker",
                "topic": "hall/temperature",
            },
        ],
    )
    labels = CatalogueLabels(document, BINDINGS)
    assert labels.entity("line") == "Line 1"
    assert labels.entity("hall") == "Plant MQTT"
    assert labels.entity("removed") == "removed"
    assert labels.reading("line", "temperature") == "Temperature"
    assert labels.reading("line", "pressure") == "pressure"


async def test_gateway_forwards_the_query_as_json(monkeypatch):
    request = AsyncMock(return_value={})
    monkeypatch.setattr(gateway.tactic, "request", request)
    await gateway.query_anomalies(
        AnomalyQuery(stream_ids=["line-temperature"], max_p_value=0.01)
    )
    sent = request.await_args.kwargs
    assert request.await_args.kwargs["endpoint"] == "/api/v1/data/anomalies/query"
    assert sent["json_data"]["stream_ids"] == ["line-temperature"]
    assert sent["json_data"]["max_p_value"] == 0.01
    assert sent["json_data"]["limit"] == 200


async def test_an_empty_or_unknown_scope_answers_without_reading_alarms():
    repository = AsyncMock()
    service = AnomalyService(AsyncMock(), repository)
    catalogue = SystemSnapshot(
        revision=1,
        storage_origin="saved",
        document=SystemDocument(),
        runtime=SystemRuntime(bindings=BINDINGS),
    )
    for stream_ids, unknown in (([], []), (["gone"], ["gone"])):
        page = await service.query(AnomalyQuery(stream_ids=stream_ids), catalogue)
        assert page.items == [] and page.summary.count == 0
        assert page.unknown_stream_ids == unknown
    assert repository.mock_calls == []
