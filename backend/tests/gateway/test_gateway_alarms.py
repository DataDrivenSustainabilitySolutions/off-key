"""Alarms are read, recorded and removed by catalogue id, and a recorded alarm
emails its catalogue names."""

from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway.api.v1 import alarms
from off_key_api_gateway.facades import tactic as facade

from tests.support.gateway import gateway_app, member_profile
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


@pytest.fixture
def remote(monkeypatch):
    request = AsyncMock(return_value=[])
    monkeypatch.setattr(facade.tactic, "request", request)
    return request


def client():
    return asgi_client(gateway_app(member_profile("admin")))


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-0.1, 1.5, "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("inferred", [False, True])
async def test_invalid_probabilities_are_rejected_before_forwarding(
    remote, value, inferred
):
    payload = {
        "reading_ids": ["r1"],
        "timestamp": CREATED["timestamp"],
        "alarm_type": "ml_conformal_static_probe",
        "value": value,
    }
    if not inferred:
        payload["value_type"] = "conformal_pvalue"
    async with client() as http:
        response = await http.post("/v1/alarms", json=payload)
    assert response.status_code == 422
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_alarms_of_a_device_or_of_readings_are_forwarded(remote):
    async with client() as http:
        assert (await http.get("/v1/alarms")).status_code == 200
        assert remote.await_args.kwargs == {
            "method": "GET",
            "endpoint": "/api/v1/data/alarms",
            "params": {"limit": 500},
        }
        response = await http.get(
            "/v1/alarms",
            params={"reading_id": ["r1", "r2"], "monitor_id": "m1", "limit": 20},
        )
        assert response.status_code == 200
        assert remote.await_args.kwargs["params"] == {
            "stream_id": ["r1", "r2"],
            "service_id": "m1",
            "limit": 20,
        }
        await http.get("/v1/alarms", params={"device_id": "pump"})
        assert remote.await_args.kwargs["params"] == {
            "device_id": "pump",
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
async def test_an_inconsistent_alarm_scope_is_rejected(remote, params, detail):
    async with client() as http:
        response = await http.get("/v1/alarms", params=params)

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_recorded_alarm_is_forwarded_as_json_and_emailed(remote, monkeypatch):
    remote.return_value = CREATED
    mail = AsyncMock(side_effect=RuntimeError("smtp down"))
    monkeypatch.setattr(alarms, "send_alarm_email", mail)
    body = {
        "reading_ids": ["pump:flow"],
        "timestamp": "2026-11-06T12:00:00Z",
        "alarm_type": "spike",
        "value": 3,
    }
    async with client() as http:
        response = await http.post("/v1/alarms", json=body)

    # A failed email does not undo the alarm.
    assert response.status_code == 201
    assert response.json() == CREATED
    assert remote.await_args.kwargs == {
        "method": "POST",
        "endpoint": "/api/v1/data/alarms",
        "json_data": {
            **body,
            "timestamp": "2026-11-06T12:00:00Z",
            "value": 3.0,
            "value_type": None,
        },
    }
    assert mail.await_args.args[0].device_label == "Pump 3"


@pytest.mark.asyncio
async def test_query_parameters_no_longer_record_an_alarm(remote):
    async with client() as http:
        response = await http.post(
            "/v1/alarms",
            params={"reading_ids": "pump:flow", "alarm_type": "x", "value": 1},
        )

    assert response.status_code == 422
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_removing_an_alarm_answers_no_content(remote):
    remote.return_value = ""
    async with client() as http:
        response = await http.delete("/v1/alarms/a 1")

    assert response.status_code == 204
    assert remote.await_args.kwargs == {
        "method": "DELETE",
        "endpoint": "/api/v1/data/alarms/a%201",
    }


@pytest.mark.asyncio
async def test_event_detail_and_reviewed_deletion_are_forwarded(remote):
    async with client() as http:
        remote.return_value = {"alarm": CREATED, "evidence": None}
        response = await http.get("/v1/alarms/a%201")
        assert response.status_code == 200
        assert response.json()["alarm"] == CREATED
        assert remote.await_args.kwargs == {
            "method": "GET",
            "endpoint": "/api/v1/data/alarms/a%201",
        }
        remote.return_value = {
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
        forwarded = remote.await_args.kwargs
        assert forwarded["endpoint"] == "/api/v1/data/alarms/deletion-preview"
        assert forwarded["json_data"]["exclude_ids"] == ["keep"]
        assert forwarded["json_data"]["query"]["reading_ids"] == ["r1"]
        assert forwarded["json_data"]["query"]["max_p_value"] == 0.001
        remote.return_value = {"count": 1501}
        response = await http.post("/v1/alarms/delete", json={"token": "preview"})
        assert response.json() == {"count": 1501}
        assert remote.await_args.kwargs == {
            "method": "POST",
            "endpoint": "/api/v1/data/alarms/delete",
            "json_data": {"token": "preview"},
        }


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
async def test_ambiguous_or_empty_deletions_never_reach_tactic(remote, payload):
    async with client() as http:
        response = await http.post("/v1/alarms/deletion-preview", json=payload)
    assert response.status_code == 422
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_readers_can_open_events_but_cannot_prepare_or_commit_deletions(remote):
    async with asgi_client(gateway_app(member_profile("user"))) as http:
        remote.return_value = {"alarm": CREATED, "evidence": None}
        assert (await http.get("/v1/alarms/a1")).status_code == 200
        remote.reset_mock()
        for endpoint, body in [
            ("deletion-preview", {"query": {}}),
            ("delete", {"token": "preview"}),
        ]:
            response = await http.post(f"/v1/alarms/{endpoint}", json=body)
            assert response.status_code == 403
        remote.assert_not_awaited()
