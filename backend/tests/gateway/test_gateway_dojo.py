"""Dojo routes: raw CSV uploads, bounded queries and who may change what."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway import providers
from off_key_api_gateway.api.v1 import dojo
from off_key_core.schemas import dojo as dojo_schemas
from off_key_core.schemas.dojo import RunAlignment

from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client
from tests.support.pipelines import quick

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
def dojo_services():
    return SimpleNamespace(
        datasets=AsyncMock(), labels=AsyncMock(), runs=AsyncMock(), metrics=AsyncMock()
    )


@pytest.fixture
def api(dojo_services):
    def client(caller=None):
        return asgi_client(
            gateway_app(
                caller or member("admin"),
                overrides={
                    providers.get_dojo_datasets: returning(dojo_services.datasets),
                    providers.get_dojo_labels: returning(dojo_services.labels),
                    providers.get_dojo_runs: returning(dojo_services.runs),
                    providers.get_dojo_metrics: returning(dojo_services.metrics),
                },
            )
        )

    return client


def asked(dojo_services) -> list:
    return [
        call for service in vars(dojo_services).values() for call in service.mock_calls
    ]


@pytest.mark.asyncio
async def test_a_csv_upload_reaches_the_import_unchanged(api, dojo_services):
    dojo_services.datasets.import_csv.return_value = DATASET
    async with api() as client:
        response = await client.post(
            "/v1/dojo/datasets/csv",
            params={"name": "Trip", "layout": "long"},
            content=b"series,timestamp,value\na,1,2\n",
        )
    assert response.status_code == 201, response.text
    body, query = dojo_services.datasets.import_csv.await_args.args
    assert body == b"series,timestamp,value\na,1,2\n"
    assert query.model_dump(exclude_none=True) == {
        "name": "Trip",
        "description": "",
        "layout": "long",
        "series_column": "series",
        "value_column": "value",
    }
    assert dojo_services.datasets.import_csv.await_args.kwargs == {"created_by": 17}


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused_before_it_is_read(
    api, dojo_services, monkeypatch
):
    monkeypatch.setattr(dojo, "MAX_UPLOAD_BYTES", 8)
    async with api() as client:
        response = await client.post(
            "/v1/dojo/datasets/csv",
            params={"name": "Big"},
            content=b"t,a\n1,1\n2,2\n",
        )
    assert response.status_code == 413
    assert asked(dojo_services) == []


@pytest.mark.asyncio
async def test_members_without_the_dojo_are_refused(api, dojo_services):
    async with api(member("user")) as client:
        response = await client.get("/v1/dojo/datasets")
    assert response.status_code == 403
    assert asked(dojo_services) == []


@pytest.mark.asyncio
async def test_a_run_is_created_with_its_bindings_and_alignment(api, dojo_services):
    dojo_services.runs.create.return_value = {
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
    body = {
        "dataset_id": "d1",
        "definition": quick().model_dump(mode="json"),
        "bindings": {"voltage": "s1", "current": "s2", "temperature": "s3"},
    }
    async with api() as client:
        response = await client.post("/v1/dojo/runs", json=body)
    assert response.status_code == 201, response.text
    [run] = dojo_services.runs.create.await_args.args
    assert run.bindings == body["bindings"]
    assert run.alignment == RunAlignment()
    assert dojo_services.runs.create.await_args.kwargs == {"created_by": 17}


@pytest.mark.asyncio
async def test_label_suggestions_take_the_gap(api, dojo_services):
    dojo_services.labels.suggestions.return_value = {"items": [], "truncated": False}
    async with api() as client:
        response = await client.get(
            "/v1/dojo/datasets/d1/label-suggestions?gap_seconds=60"
        )
        refused = await client.get(
            "/v1/dojo/datasets/d1/label-suggestions?gap_seconds=-1"
        )
    assert response.status_code == 200, response.text
    dataset_id, query = dojo_services.labels.suggestions.await_args.args
    assert (dataset_id, query.gap_seconds) == ("d1", 60.0)
    assert refused.status_code == 422
    assert dojo_services.labels.suggestions.await_count == 1


@pytest.mark.asyncio
async def test_a_run_outline_takes_the_number_of_stretches(api, dojo_services):
    outline = {
        "run_id": "r1",
        "strategy": "adaptive_stream",
        "start_at": None,
        "end_at": None,
        "bucket_seconds": 0.0,
        "buckets": [],
    }
    dojo_services.runs.outline.return_value = outline
    async with api() as client:
        response = await client.get("/v1/dojo/runs/r1/outline?buckets=120")
        default = await client.get("/v1/dojo/runs/r1/outline")
        refused = await client.get("/v1/dojo/runs/r1/outline?buckets=0")
        beyond = await client.get(
            f"/v1/dojo/runs/r1/outline?buckets={dojo_schemas.MAX_OUTLINE_BUCKETS + 1}"
        )
    assert response.status_code == 200, response.text
    assert response.json() == outline
    assert [
        (call.args[0], call.args[1].buckets)
        for call in dojo_services.runs.outline.await_args_list
    ] == [("r1", 120), ("r1", 300)]
    assert default.status_code == 200
    assert (refused.status_code, beyond.status_code) == (422, 422)


@pytest.mark.asyncio
async def test_the_sampled_steps_of_a_run_are_read(api, dojo_services):
    steps = {
        "run_id": "r1",
        "samples": [
            {
                "sequence": 7,
                "timestamp": "2026-03-01T00:07:00Z",
                "phase": "operational",
                "steps": {
                    "scaler": {
                        "input": {"voltage": 231.5},
                        "output": {"voltage": 0.4},
                        "state": "ready",
                        "reason": None,
                    },
                    "detector": {
                        "input": None,
                        "output": None,
                        "state": "initializing",
                        "reason": "Needs 50 values before its first output",
                    },
                },
            }
        ],
    }
    dojo_services.runs.steps.return_value = steps
    async with api() as client:
        response = await client.get("/v1/dojo/runs/r1/steps")
    assert response.status_code == 200, response.text
    assert response.json() == steps
    assert dojo_services.runs.steps.await_args.args == ("r1",)


@pytest.mark.asyncio
async def test_a_label_batch_is_one_write(api, dojo_services):
    dojo_services.labels.create_many.return_value = []
    label = {"start_at": "2026-03-01T00:00:00Z", "end_at": "2026-03-01T00:01:00Z"}
    async with api() as client:
        response = await client.post(
            "/v1/dojo/datasets/d1/labels/batch", json={"labels": [label] * 3}
        )
        empty = await client.post(
            "/v1/dojo/datasets/d1/labels/batch", json={"labels": []}
        )
    assert response.status_code == 201, response.text
    dataset_id, labels = dojo_services.labels.create_many.await_args.args
    assert (dataset_id, len(labels)) == ("d1", 3)
    assert dojo_services.labels.create_many.await_count == 1
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_a_comparison_takes_each_run_id_once(api, dojo_services):
    dojo_services.metrics.compare.return_value = {
        "dataset_id": "d1",
        "labels": [],
        "runs": [],
    }
    async with api() as client:
        response = await client.get(
            "/v1/dojo/datasets/d1/comparison?run_ids=r1&run_ids=r2"
        )
        refused = await client.get(
            "/v1/dojo/datasets/d1/comparison?run_ids=r1&run_ids=r1"
        )
    assert response.status_code == 200, response.text
    dataset_id, query = dojo_services.metrics.compare.await_args.args
    assert (dataset_id, query.run_ids) == ("d1", ["r1", "r2"])
    assert dojo_services.metrics.compare.await_count == 1
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_promoting_a_run_needs_manage_monitors_too(api, dojo_services):
    dojo_services.runs.promote.return_value = {
        "pipeline_id": "p1",
        "pipeline_name": "Final",
        "bindings": [],
    }
    async with api(member("trainer", permissions=["use_dojo"])) as client:
        refused = await client.post("/v1/dojo/runs/r1/promote", json={"name": "Final"})
    async with api() as client:
        response = await client.post("/v1/dojo/runs/r1/promote", json={"name": "Final"})
    assert refused.status_code == 403
    assert response.status_code == 201, response.text
    run_id, promotion = dojo_services.runs.promote.await_args.args
    assert run_id == "r1"
    assert promotion.model_dump() == {"name": "Final", "description": ""}
    assert dojo_services.runs.promote.await_count == 1
