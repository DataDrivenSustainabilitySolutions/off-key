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
