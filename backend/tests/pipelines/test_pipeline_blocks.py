"""Blocks: saved chains of steps, their limits, their routes and their library."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from off_key_api_gateway.api.v1 import pipelines as gateway_pipelines
from off_key_core.auth.permissions import Permission
from off_key_core.db.base import get_db_async
from off_key_core.models.pipeline_blocks import require_block_steps
from off_key_core.schemas.pipelines import (
    MAX_BLOCK_BYTES,
    MAX_BLOCK_STEPS,
    MAX_BLOCKS,
    PipelineBlockCreate,
    PipelineBlockList,
    PipelineBlockStep,
)
from off_key_tactic_middleware.api import collection_auth
from off_key_tactic_middleware.api.v1 import pipelines as tactic_pipelines
from off_key_tactic_middleware.config.config import get_tactic_settings
from off_key_tactic_middleware.domain import ConflictError, NotFoundError
from off_key_tactic_middleware.provider import get_pipeline_blocks
from off_key_tactic_middleware.services.pipelines import blocks as block_library
from off_key_tactic_middleware.services.pipelines.blocks import PipelineBlocks
from pydantic import ValidationError

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client

TOKEN = {"Authorization": "Bearer member-token"}
SCALE = {"component": "static.standard_scaler"}
POWER = {
    "component": "prepare.formula",
    "params": {"expression": "voltage * current", "name": "power"},
    "label": "Power",
}
STORED = {
    "id": "block-1",
    "name": "Power, scaled",
    "description": "",
    "steps": [
        {**POWER, "contract_version": 1},
        {**SCALE, "contract_version": 1, "params": {}, "label": None},
    ],
    "created_at": "2026-11-12T09:00:00Z",
}


def block(name="Power, scaled", steps=(POWER, SCALE), **fields) -> PipelineBlockCreate:
    return PipelineBlockCreate(name=name, steps=list(steps), **fields)


def steps(*items) -> list[PipelineBlockStep]:
    return [PipelineBlockStep.model_validate(item) for item in items]


def test_a_block_holds_steps_that_take_and_give_features():
    require_block_steps(steps(POWER, SCALE, {"component": "adaptive.expected_value"}))

    for component, reason in [
        ("detector:pyod_iforest", "cannot be part of a block"),
        ("features.merge", "cannot be part of a block"),
        ("source.aligned", "cannot be part of a block"),
        ("calibrate.fixed_split", "cannot be part of a block"),
        ("policy.martingale", "cannot be part of a block"),
        ("output.evidence", "cannot be part of a block"),
        ("prepare.unknown", "prepare.unknown is not a step this version offers"),
    ]:
        with pytest.raises(ValueError, match=reason):
            require_block_steps(steps(SCALE, {"component": component}))
    with pytest.raises(ValueError, match="not a step this version offers"):
        require_block_steps(steps({**SCALE, "contract_version": 2}))


def test_a_block_is_named_and_bounded():
    assert block(name="  Power, scaled  ").name == "Power, scaled"
    assert len(block(steps=[SCALE] * MAX_BLOCK_STEPS).steps) == MAX_BLOCK_STEPS

    with pytest.raises(ValidationError, match="Enter a block name"):
        block(name="   ")
    with pytest.raises(ValidationError):
        block(steps=[])
    with pytest.raises(ValidationError):
        block(steps=[SCALE] * (MAX_BLOCK_STEPS + 1))
    long = {"component": "prepare.formula", "params": {"expression": "x" * 1024}}
    with pytest.raises(ValidationError, match="at most 16 KiB of settings"):
        block(steps=[long] * MAX_BLOCK_STEPS)
    assert MAX_BLOCK_BYTES == 16 * 1024


def tactic_app(blocks) -> FastAPI:
    async def session():
        yield SimpleNamespace()

    app = FastAPI()
    app.include_router(tactic_pipelines.router, prefix="/api/v1")
    member = SimpleNamespace(email="member@example.com", role="admin")
    app.dependency_overrides.update(
        {
            get_db_async: session,
            get_pipeline_blocks: lambda: blocks,
            collection_auth.current_caller: lambda: member,
            collection_auth.require_permission(Permission.manage_monitors): (
                lambda: member
            ),
        }
    )
    return app


@pytest.mark.asyncio
async def test_tactic_serves_the_block_library():
    saved, removed = [], []

    async def listed():
        return PipelineBlockList(items=[STORED])

    async def create(change):
        saved.append(change)
        return STORED

    async def remove(identifier):
        removed.append(identifier)

    library = SimpleNamespace(list=listed, create=create, remove=remove)
    async with asgi_client(tactic_app(library)) as client:
        listing = await client.get("/api/v1/monitors/pipeline-blocks")
        created = await client.post(
            "/api/v1/monitors/pipeline-blocks",
            json={"name": " Power, scaled ", "steps": [POWER, SCALE]},
        )
        deleted = await client.delete("/api/v1/monitors/pipeline-blocks/block-1")
        unnamed = await client.post(
            "/api/v1/monitors/pipeline-blocks", json={"name": " ", "steps": [SCALE]}
        )

    assert listing.status_code == 200 and listing.json()["items"][0]["id"] == "block-1"
    assert created.status_code == 201 and created.json()["steps"][0]["label"] == "Power"
    assert saved == [block()]
    assert deleted.status_code == 204 and removed == ["block-1"]
    assert unnamed.status_code == 422 and len(saved) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "error", "status"),
    [
        ("POST", ValueError("Isolation Forest cannot be part of a block."), 422),
        ("POST", ConflictError("A block named Power already exists."), 409),
        ("DELETE", ConflictError("Pipeline authoring is disabled"), 409),
        ("DELETE", NotFoundError("Block not found"), 404),
    ],
)
async def test_tactic_says_why_a_block_was_refused(method, error, status):
    async def fail(*_args):
        raise error

    library = SimpleNamespace(create=fail, remove=fail)
    async with asgi_client(tactic_app(library)) as client:
        response = await (
            client.post(
                "/api/v1/monitors/pipeline-blocks",
                json={"name": "Power", "steps": [SCALE]},
            )
            if method == "POST"
            else client.delete("/api/v1/monitors/pipeline-blocks/block-1")
        )

    assert (response.status_code, response.json()) == (status, {"detail": str(error)})


@pytest.fixture
def forwarded(monkeypatch):
    recorded = []

    async def request(method, endpoint, **kwargs):
        recorded.append((method, endpoint, kwargs))
        return {"items": [STORED]} if method == "GET" else STORED

    monkeypatch.setattr(gateway_pipelines.tactic, "request", request)
    return recorded


@pytest.mark.asyncio
async def test_any_member_lists_blocks_through_the_gateway(forwarded):
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        response = await client.get("/v1/pipeline-blocks", headers=TOKEN)

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [STORED]}
    [(method, endpoint, kwargs)] = forwarded
    assert (method, endpoint) == ("GET", "/api/v1/monitors/pipeline-blocks")
    assert kwargs["headers"] == TOKEN


@pytest.mark.asyncio
async def test_saving_and_deleting_a_block_need_manage_monitors(forwarded):
    body = {"name": "Power, scaled", "steps": [POWER, SCALE]}
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        refused = [
            await client.post("/v1/pipeline-blocks", json=body, headers=TOKEN),
            await client.delete("/v1/pipeline-blocks/block-1", headers=TOKEN),
        ]
    assert [response.status_code for response in refused] == [403, 403]
    assert forwarded == []

    member = member_profile("user", permissions=[Permission.manage_monitors])
    async with asgi_client(gateway_app(member)) as client:
        created = await client.post("/v1/pipeline-blocks", json=body, headers=TOKEN)
        deleted = await client.delete("/v1/pipeline-blocks/a%20b", headers=TOKEN)

    assert created.status_code == 201 and created.json() == STORED
    assert deleted.status_code == 204 and deleted.content == b""
    assert [(method, endpoint) for method, endpoint, _ in forwarded] == [
        ("POST", "/api/v1/monitors/pipeline-blocks"),
        ("DELETE", "/api/v1/monitors/pipeline-blocks/a%20b"),
    ]
    assert forwarded[0][2]["json_data"] == block().model_dump(mode="json")


@pytest.mark.asyncio
async def test_blocks_are_saved_listed_by_name_and_deleted(pipeline_database):
    async with pipeline_database() as session:
        library = PipelineBlocks(session)
        scaled = await library.create(block(description="Power in standard units"))
        await library.create(block(name="clip", steps=[{"component": "prepare.range"}]))
        await library.create(block(name="Alpha", steps=[SCALE]))

    async with pipeline_database() as session:
        library = PipelineBlocks(session)
        listed = (await library.list()).items
        assert [item.name for item in listed] == ["Alpha", "clip", "Power, scaled"]
        assert listed[2] == scaled
        assert scaled.description == "Power in standard units"
        assert [step.model_dump() for step in scaled.steps] == [
            {**POWER, "contract_version": 1},
            {**SCALE, "contract_version": 1, "params": {}, "label": None},
        ]

        await library.remove(scaled.id)
        assert [item.name for item in (await library.list()).items] == ["Alpha", "clip"]
        with pytest.raises(NotFoundError, match="Block not found"):
            await library.remove(scaled.id)


@pytest.mark.asyncio
async def test_a_block_name_is_taken_once_and_the_library_is_bounded(
    pipeline_database, monkeypatch
):
    async with pipeline_database() as session:
        library = PipelineBlocks(session)
        await library.create(block())
        with pytest.raises(ConflictError, match="A block named Power, scaled already"):
            await library.create(block(steps=[SCALE]))
        with pytest.raises(ValueError, match="cannot be part of a block"):
            await library.create(
                block(name="Model", steps=[{"component": "detector:pyod_iforest"}])
            )

        monkeypatch.setattr(block_library, "MAX_BLOCKS", 2)
        await library.create(block(name="Second"))
        with pytest.raises(ConflictError, match="The library holds 2 blocks"):
            await library.create(block(name="Third"))
        assert len((await library.list()).items) == 2
    assert MAX_BLOCKS == 100


@pytest.mark.asyncio
async def test_blocks_are_not_changed_while_authoring_is_off(
    pipeline_database, monkeypatch
):
    async with pipeline_database() as session:
        library = PipelineBlocks(session)
        saved = await library.create(block())
        monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "false")
        get_tactic_settings.cache_clear()

        with pytest.raises(ConflictError, match="authoring is disabled"):
            await library.create(block(name="Other"))
        with pytest.raises(ConflictError, match="authoring is disabled"):
            await library.remove(saved.id)
        assert [item.id for item in (await library.list()).items] == [saved.id]
