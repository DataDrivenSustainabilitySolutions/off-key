"""The gateway's routes for finding components and for editing a design in
small steps, answered by TACTIC's own handlers behind the hop."""

import pytest
from fastapi import HTTPException
from off_key_api_gateway.api.v1 import pipelines
from off_key_core.auth.permissions import Permission
from off_key_core.schemas.pipeline_tools import ComponentSearchQuery, DesignEditRequest
from off_key_tactic_middleware.api.v1 import pipelines as tactic_pipelines

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client
from tests.support.pipelines import template

TOKEN = {"Authorization": "Bearer member-token"}
DESIGNER = member_profile("user", permissions=[Permission.manage_monitors])


@pytest.fixture
def calls(monkeypatch):
    """What the gateway sends on, answered as TACTIC answers it."""
    recorded = []

    async def request(method, endpoint, json_data=None, params=None, headers=None):
        recorded.append((method, endpoint, headers))
        if endpoint.endswith("/catalog/search"):
            query = ComponentSearchQuery.model_validate(params or {})
            answer = await tactic_pipelines.search_catalog(query)
        else:
            change = DesignEditRequest.model_validate(json_data)
            answer = await tactic_pipelines.edit_unsaved_design(change)
        return answer.model_dump(mode="json")

    monkeypatch.setattr(pipelines.tactic, "request", request)
    return recorded


@pytest.mark.asyncio
async def test_any_member_finds_components_by_purpose(calls):
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        response = await client.get(
            "/v1/pipeline-components/search",
            params={"query": "calm noise", "group": "prepare", "limit": 3},
            headers=TOKEN,
        )
        refused = await client.get(
            "/v1/pipeline-components/search", params={"limit": 0}, headers=TOKEN
        )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert page["components"][0]["id"] == "prepare.smooth"
    # Short enough to read whole: no settings in full, no schema.
    assert "fields" not in page["components"][0]
    assert refused.status_code == 422
    assert calls == [("GET", "/api/v1/monitors/pipelines/catalog/search", TOKEN)]


@pytest.mark.asyncio
async def test_search_is_not_taken_for_a_component_of_that_name(calls):
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        response = await client.get("/v1/pipeline-components/search", headers=TOKEN)
    assert response.status_code == 200, response.text
    assert len(response.json()["components"]) == 10
    assert response.json()["total"] > 10


@pytest.mark.asyncio
async def test_small_edits_need_manage_monitors_and_answer_with_the_design(calls):
    body = {
        "definition": template().model_dump(mode="json"),
        "edits": [
            {
                "op": "add_step",
                "component": "prepare.smooth",
                "after": "input",
                "before": "detector",
                "params": {"window_size": 12},
            },
            {
                "op": "add_note",
                "text": "Noisy at this rate.",
                "beside": "prepare_smooth_1",
            },
            {"op": "set_settings", "training_window_size": 600},
        ],
    }
    async with asgi_client(gateway_app(member_profile("user"))) as client:
        refused = await client.post("/v1/pipelines/edit", json=body, headers=TOKEN)
    assert refused.status_code == 403
    assert calls == []
    async with asgi_client(gateway_app(DESIGNER)) as client:
        response = await client.post("/v1/pipelines/edit", json=body, headers=TOKEN)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["added"] == ["prepare_smooth_1", "note_1"]
    assert result["report"]["valid"] and result["report"]["issues"] == []
    # The design is in the form the editor reads, with its calibration step.
    definition = result["definition"]
    assert definition["schema_version"] == 2
    assert "calibration" in {node["kind"] for node in definition["nodes"]}
    smooth = next(n for n in definition["nodes"] if n["id"] == "prepare_smooth_1")
    assert smooth["params"] == {"method": "exponential", "window_size": 12}
    # What the edits left alone came through the hop as it was.
    assert definition["settings"]["training_window_size"] == 600
    assert definition["settings"]["seed"] == 42
    assert result["layout"]["notes"][0]["text"] == "Noisy at this rate."
    assert calls == [("POST", "/api/v1/monitors/pipelines/edit", TOKEN)]


@pytest.mark.asyncio
async def test_an_edit_that_cannot_be_made_is_refused_whole(calls):
    with pytest.raises(HTTPException) as refusal:
        await tactic_pipelines.edit_unsaved_design(
            DesignEditRequest.model_validate(
                {
                    "definition": template().model_dump(mode="json"),
                    "edits": [
                        {"op": "set_settings", "seed": 7},
                        {"op": "remove_step", "id": "gone"},
                    ],
                }
            )
        )
    assert refusal.value.status_code == 422
    assert refusal.value.detail == (
        "Edit 2 (remove_step): The design has no step 'gone'"
    )
    # A request that names no edit, or an edit the gateway does not know,
    # never reaches TACTIC.
    async with asgi_client(gateway_app(DESIGNER)) as client:
        for body in ({"edits": []}, {"edits": [{"op": "rename_step", "id": "a"}]}):
            response = await client.post("/v1/pipelines/edit", json=body, headers=TOKEN)
            assert response.status_code == 422
    assert calls == []
