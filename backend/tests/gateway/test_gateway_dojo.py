"""The gateway forwards Dojo uploads as raw CSV and refuses oversized bodies."""

from datetime import UTC, datetime

import pytest
from off_key_api_gateway.api.v1 import dojo

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client

TOKEN = {"Authorization": "Bearer member-token"}
DATASET = {
    "id": "d1",
    "name": "Trip",
    "description": "",
    "origin": "csv",
    "point_count": 1,
    "series_count": 1,
    "start_at": None,
    "end_at": None,
    "created_by": 17,
    "created_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
    "source": {},
    "series": [],
}


@pytest.fixture
def calls(monkeypatch):
    recorded = []

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return DATASET

    monkeypatch.setattr(dojo.tactic, "request", request)
    return recorded


@pytest.mark.asyncio
async def test_csv_upload_is_forwarded_unchanged_with_the_callers_token(calls):
    app = gateway_app(member_profile("admin"))
    async with asgi_client(app) as client:
        response = await client.post(
            "/v1/dojo/datasets/csv",
            params={"name": "Trip", "layout": "long"},
            content=b"series,timestamp,value\na,1,2\n",
            headers=TOKEN,
        )
    assert response.status_code == 201, response.text
    [(method, endpoint, kwargs)] = calls
    assert (method, endpoint) == ("POST", "/api/v1/dojo/datasets/csv")
    assert kwargs["content"] == b"series,timestamp,value\na,1,2\n"
    assert kwargs["content_type"] == "text/csv"
    assert kwargs["params"] == {
        "name": "Trip",
        "description": "",
        "layout": "long",
        "series_column": "series",
        "value_column": "value",
    }
    assert kwargs["headers"] == TOKEN


@pytest.mark.asyncio
async def test_oversized_upload_is_refused_before_reaching_tactic(calls, monkeypatch):
    monkeypatch.setattr(dojo, "MAX_UPLOAD_BYTES", 8)
    app = gateway_app(member_profile("admin"))
    async with asgi_client(app) as client:
        response = await client.post(
            "/v1/dojo/datasets/csv",
            params={"name": "Big"},
            content=b"t,a\n1,1\n2,2\n",
            headers=TOKEN,
        )
    assert response.status_code == 413
    assert calls == []


@pytest.mark.asyncio
async def test_members_without_the_administrator_role_are_refused(calls):
    app = gateway_app(member_profile("user"))
    async with asgi_client(app) as client:
        response = await client.get("/v1/dojo/datasets", headers=TOKEN)
    assert response.status_code == 403
    assert calls == []


@pytest.mark.asyncio
async def test_run_creation_is_forwarded_as_json(monkeypatch):
    from off_key_core.schemas.dojo import RunAlignment

    from tests.support.pipelines import quick

    recorded = []
    run = {
        "id": "r1",
        "dataset_id": "d1",
        "name": "",
        "status": "queued",
        "strategy": "adaptive_stream",
        "points_total": 3,
        "points_read": 0,
        "result_count": 0,
        "alarm_count": 0,
        "error": None,
        "created_by": 17,
        "created_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
        "started_at": None,
        "finished_at": None,
        "definition": {},
        "bindings": [],
        "alignment": RunAlignment().model_dump(),
        "cancel_requested": False,
        "stats": {},
    }

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return run

    monkeypatch.setattr(dojo.tactic, "request", request)
    body = {
        "dataset_id": "d1",
        "definition": quick().model_dump(mode="json"),
        "bindings": {"voltage": "s1", "current": "s2", "temperature": "s3"},
    }
    async with asgi_client(gateway_app(member_profile("admin"))) as client:
        response = await client.post("/v1/dojo/runs", json=body, headers=TOKEN)
    assert response.status_code == 201, response.text
    [(method, endpoint, kwargs)] = recorded
    assert (method, endpoint) == ("POST", "/api/v1/dojo/runs")
    assert kwargs["json_data"]["bindings"] == body["bindings"]
    assert kwargs["json_data"]["alignment"] == RunAlignment().model_dump()


@pytest.mark.asyncio
async def test_label_suggestions_forward_the_gap(monkeypatch):
    recorded = []

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return {"items": [], "truncated": False}

    monkeypatch.setattr(dojo.tactic, "request", request)
    async with asgi_client(gateway_app(member_profile("admin"))) as client:
        response = await client.get(
            "/v1/dojo/datasets/d1/label-suggestions?gap_seconds=60", headers=TOKEN
        )
        refused = await client.get(
            "/v1/dojo/datasets/d1/label-suggestions?gap_seconds=-1", headers=TOKEN
        )
    assert response.status_code == 200, response.text
    [(method, endpoint, kwargs)] = recorded
    assert (method, endpoint) == ("GET", "/api/v1/dojo/datasets/d1/label-suggestions")
    assert kwargs["params"] == {"gap_seconds": 60.0}
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_a_comparison_forwards_each_run_id(monkeypatch):
    recorded = []

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return {"dataset_id": "d1", "labels": [], "runs": []}

    monkeypatch.setattr(dojo.tactic, "request", request)
    async with asgi_client(gateway_app(member_profile("admin"))) as client:
        response = await client.get(
            "/v1/dojo/datasets/d1/comparison?run_ids=r1&run_ids=r2", headers=TOKEN
        )
        refused = await client.get(
            "/v1/dojo/datasets/d1/comparison?run_ids=r1&run_ids=r1", headers=TOKEN
        )
    assert response.status_code == 200, response.text
    [(method, endpoint, kwargs)] = recorded
    assert (method, endpoint) == ("GET", "/api/v1/dojo/datasets/d1/comparison")
    assert kwargs["params"] == {"run_ids": ["r1", "r2"]}
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_promoting_a_run_needs_manage_monitors_too(monkeypatch):
    recorded = []
    promotion = {"pipeline_id": "p1", "pipeline_name": "Final", "bindings": []}

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return promotion

    monkeypatch.setattr(dojo.tactic, "request", request)
    trainer = member_profile("trainer", permissions=["use_dojo"])
    async with asgi_client(gateway_app(trainer)) as client:
        refused = await client.post(
            "/v1/dojo/runs/r1/promote", json={"name": "Final"}, headers=TOKEN
        )
    async with asgi_client(gateway_app(member_profile("admin"))) as client:
        response = await client.post(
            "/v1/dojo/runs/r1/promote", json={"name": "Final"}, headers=TOKEN
        )
    assert refused.status_code == 403
    assert response.status_code == 201, response.text
    [(method, endpoint, kwargs)] = recorded
    assert (method, endpoint) == ("POST", "/api/v1/dojo/runs/r1/promote")
    assert kwargs["json_data"] == {"name": "Final", "description": ""}
