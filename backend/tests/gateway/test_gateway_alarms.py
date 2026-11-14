"""Alarms are read, recorded and removed by catalogue id, and a recorded alarm
emails its catalogue names."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway import providers
from off_key_api_gateway.api.v1 import alarms

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client

CREATED = {
    "alarm_id": "a1",
    "timestamp": "2026-11-06T12:00:00Z",
    "device_id": "pump",
    "device_label": "Pump 3",
    "reading_ids": ["pump:flow"],
    "reading_labels": {"pump:flow": "Flow"},
    "multivariate": False,
    "alarm_type": "spike",
    "value": 3.0,
    "value_type": "zscore",
    "monitor_id": None,
}
CATALOGUE = object()


@pytest.fixture
def stores():
    """The alarm store, its reviewed actions and the catalogue they name."""
    system = AsyncMock()
    system.read.return_value = CATALOGUE
    return SimpleNamespace(alarms=AsyncMock(), actions=AsyncMock(), system=system)


def client(stores, role="admin"):
    return asgi_client(
        gateway_app(
            member(role),
            overrides={
                providers.get_alarm_service: returning(stores.alarms),
                providers.get_alarm_actions: returning(stores.actions),
                providers.get_system_service: returning(stores.system),
            },
        )
    )


def untouched(stores) -> bool:
    return stores.alarms.mock_calls == [] and stores.actions.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-0.1, 1.5, "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("inferred", [False, True])
async def test_invalid_probabilities_are_refused_before_anything_is_stored(
    stores, value, inferred
):
    payload = {
        "reading_ids": ["r1"],
        "timestamp": CREATED["timestamp"],
        "alarm_type": "ml_conformal_static_probe",
        "value": value,
    }
    if not inferred:
        payload["value_type"] = "conformal_pvalue"
    async with client(stores) as http:
        response = await http.post("/v1/alarms", json=payload)
    assert response.status_code == 422
    assert untouched(stores)


@pytest.mark.asyncio
async def test_alarms_of_a_device_or_of_readings_are_read_by_catalogue_id(stores):
    stores.alarms.list_alarms.return_value = []
    async with client(stores) as http:
        assert (await http.get("/v1/alarms")).status_code == 200
        assert stores.alarms.list_alarms.await_args.args == (CATALOGUE,)
        assert stores.alarms.list_alarms.await_args.kwargs == {
            "device_id": None,
            "stream_ids": None,
            "service_id": None,
            "limit": 500,
        }
        response = await http.get(
            "/v1/alarms",
            params={"reading_id": ["r1", "r2"], "monitor_id": "m1", "limit": 20},
        )
        assert response.status_code == 200
        assert stores.alarms.list_alarms.await_args.kwargs == {
            "device_id": None,
            "stream_ids": ["r1", "r2"],
            "service_id": "m1",
            "limit": 20,
        }
        await http.get("/v1/alarms", params={"device_id": "pump"})
        assert stores.alarms.list_alarms.await_args.kwargs == {
            "device_id": "pump",
            "stream_ids": None,
            "service_id": None,
            "limit": 500,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "detail"),
    [
        (
            {"device_id": "pump", "reading_id": "r1"},
            "Name either device_id or reading_id",
        ),
        ({"reading_id": [f"r{n}" for n in range(201)]}, "Name at most 200 readings"),
    ],
)
async def test_an_inconsistent_alarm_scope_is_refused(stores, params, detail):
    async with client(stores) as http:
        response = await http.get("/v1/alarms", params=params)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert untouched(stores)


@pytest.mark.asyncio
async def test_a_recorded_alarm_is_stored_and_emailed(stores, monkeypatch):
    stores.alarms.create_alarm.return_value = CREATED
    mail = AsyncMock(side_effect=RuntimeError("smtp down"))
    monkeypatch.setattr(alarms, "send_alarm_email", mail)
    body = {
        "reading_ids": ["pump:flow"],
        "timestamp": "2026-11-06T12:00:00Z",
        "alarm_type": "spike",
        "value": 3,
    }
    async with client(stores) as http:
        response = await http.post("/v1/alarms", json=body)

    # A failed email does not undo the alarm.
    assert response.status_code == 201
    assert response.json() == CREATED
    recorded, catalogue = stores.alarms.create_alarm.await_args.args
    assert catalogue is CATALOGUE
    assert (recorded.reading_ids, recorded.alarm_type, recorded.value) == (
        ["pump:flow"],
        "spike",
        3.0,
    )
    assert mail.await_args.args[0].device_label == "Pump 3"


@pytest.mark.asyncio
async def test_query_parameters_do_not_record_an_alarm(stores):
    async with client(stores) as http:
        response = await http.post(
            "/v1/alarms",
            params={"reading_ids": "pump:flow", "alarm_type": "x", "value": 1},
        )

    assert response.status_code == 422
    assert untouched(stores)


@pytest.mark.asyncio
async def test_removing_an_alarm_answers_no_content(stores):
    async with client(stores) as http:
        response = await http.delete("/v1/alarms/a 1")

    assert response.status_code == 204
    assert stores.alarms.delete_alarm.await_args.kwargs == {"alarm_id": "a 1"}


@pytest.mark.asyncio
async def test_event_detail_and_reviewed_deletion(stores):
    async with client(stores) as http:
        stores.actions.detail.return_value = {"alarm": CREATED, "evidence": None}
        response = await http.get("/v1/alarms/a%201")
        assert response.status_code == 200
        assert response.json()["alarm"] == CREATED
        assert stores.actions.detail.await_args.args == ("a 1", CATALOGUE)
        stores.actions.preview.return_value = {
            "token": "preview",
            "count": 1501,
            "expires_at": "2026-11-12T12:00:00Z",
        }
        response = await http.post(
            "/v1/alarms/deletion-preview",
            json={
                "query": {"reading_ids": ["r1"], "max_p_value": 0.001},
                "exclude_ids": ["keep"],
            },
        )
        assert response.status_code == 200
        selection, catalogue = stores.actions.preview.await_args.args
        assert catalogue is CATALOGUE
        assert selection.exclude_ids == ["keep"]
        assert selection.query.reading_ids == ["r1"]
        assert selection.query.max_p_value == 0.001
        stores.actions.delete.return_value = 1501
        response = await http.post("/v1/alarms/delete", json={"token": "preview"})
        assert response.json() == {"count": 1501}
        assert stores.actions.delete.await_args.args == ("preview",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"alarm_ids": []},
        {"alarm_ids": [""]},
        {"alarm_ids": ["one"], "query": {}},
        {"alarm_ids": ["one"], "exclude_ids": ["two"]},
        {"query": {"reading_idd": "one"}},
        {"query": {}, "excluded_ids": ["one"]},
        {"query": {"before": {"timestamp": CREATED["timestamp"], "alarm_id": "a"}}},
    ],
)
async def test_ambiguous_or_empty_deletions_are_refused(stores, payload):
    async with client(stores) as http:
        response = await http.post("/v1/alarms/deletion-preview", json=payload)
    assert response.status_code == 422
    assert untouched(stores)


@pytest.mark.asyncio
async def test_readers_can_open_events_but_cannot_prepare_or_commit_deletions(stores):
    async with client(stores, role="user") as http:
        stores.actions.detail.return_value = {"alarm": CREATED, "evidence": None}
        assert (await http.get("/v1/alarms/a1")).status_code == 200
        stores.actions.reset_mock()
        for endpoint, body in [
            ("deletion-preview", {"query": {}}),
            ("delete", {"token": "preview"}),
        ]:
            response = await http.post(f"/v1/alarms/{endpoint}", json=body)
            assert response.status_code == 403
        assert untouched(stores)
