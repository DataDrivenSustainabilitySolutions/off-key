"""The routes for finding components and for editing a design in small steps."""

import pytest
from off_key_core.auth.permissions import Permission

from tests.support.gateway import gateway_app, member
from tests.support.http import asgi_client
from tests.support.pipelines import template

DESIGNER = member("designer", permissions=[Permission.manage_monitors])


@pytest.mark.asyncio
async def test_any_member_finds_components_by_purpose():
    async with asgi_client(gateway_app(member("user"))) as client:
        response = await client.get(
            "/v1/pipeline-components/search",
            params={"query": "calm noise", "group": "prepare", "limit": 3},
        )
        refused = await client.get(
            "/v1/pipeline-components/search", params={"limit": 0}
        )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert page["components"][0]["id"] == "prepare.smooth"
    # Short enough to read whole: no settings in full, no schema.
    assert "fields" not in page["components"][0]
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_search_is_not_taken_for_a_component_of_that_name():
    async with asgi_client(gateway_app(member("user"))) as client:
        response = await client.get("/v1/pipeline-components/search")
    assert response.status_code == 200, response.text
    assert len(response.json()["components"]) == 10
    assert response.json()["total"] > 10


@pytest.mark.asyncio
async def test_small_edits_need_manage_monitors_and_answer_with_the_design():
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
    async with asgi_client(gateway_app(member("user"))) as client:
        refused = await client.post("/v1/pipelines/edit", json=body)
    assert refused.status_code == 403
    async with asgi_client(gateway_app(DESIGNER)) as client:
        response = await client.post("/v1/pipelines/edit", json=body)
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
    # What the edits left alone comes back as it was.
    assert definition["settings"]["training_window_size"] == 600
    assert definition["settings"]["seed"] == 42
    assert result["layout"]["notes"][0]["text"] == "Noisy at this rate."


@pytest.mark.asyncio
async def test_an_edit_that_cannot_be_made_is_refused_whole():
    body = {
        "definition": template().model_dump(mode="json"),
        "edits": [
            {"op": "set_settings", "seed": 7},
            {"op": "remove_step", "id": "gone"},
        ],
    }
    async with asgi_client(gateway_app(DESIGNER)) as client:
        refusal = await client.post("/v1/pipelines/edit", json=body)
        assert (refusal.status_code, refusal.json()["detail"]) == (
            422,
            "Edit 2 (remove_step): The design has no step 'gone'",
        )
        # A request that names no edit, or an edit the API does not know.
        for malformed in (
            {"edits": []},
            {"edits": [{"op": "rename_step", "id": "a"}]},
        ):
            response = await client.post("/v1/pipelines/edit", json=malformed)
            assert response.status_code == 422
