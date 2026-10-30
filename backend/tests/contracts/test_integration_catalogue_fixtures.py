"""Cleanup respects asynchronous input ownership and fresh system revisions."""

import json

import httpx
import pytest

from tests.support.integration_catalogue import RecordedEntity, remove_recorded_entity

ENTITY = RecordedEntity("owned", "owned", ("owned",), "owned", {}, {}, ())


def test_cleanup_refreshes_revision_and_preserves_unrelated_changes(monkeypatch):
    writes = []
    monkeypatch.setattr(
        "tests.support.integration_catalogue.time.sleep", lambda _: None
    )

    def route(request):
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "revision": len(writes) + 1,
                    "document": {
                        key: [{"id": "owned"}, {"id": f"other-{len(writes)}"}]
                        for key in ("streams", "devices", "connections")
                    },
                },
            )
        writes.append(json.loads(request.content))
        return httpx.Response(409 if len(writes) == 1 else 200, json={})

    with httpx.Client(
        base_url="http://fixture", transport=httpx.MockTransport(route)
    ) as client:
        remove_recorded_entity(client, ENTITY)
    assert [write["expected_revision"] for write in writes] == [1, 2]
    assert all(
        value == [{"id": "other-1"}] for value in writes[-1]["document"].values()
    )
    assert writes[-1]["pause_affected_monitors"] is True


@pytest.mark.parametrize("status", [409, 500])
def test_cleanup_reports_timeout_and_nonconflict_failures(status, monkeypatch):
    clock = iter([0, 91])
    monkeypatch.setattr(
        "tests.support.integration_catalogue.time.monotonic", lambda: next(clock)
    )
    monkeypatch.setattr(
        "tests.support.integration_catalogue.time.sleep",
        lambda _: pytest.fail("Unexpected retry"),
    )

    def route(request):
        return httpx.Response(
            200 if request.method == "GET" else status,
            json={
                "revision": 1,
                "document": {key: [] for key in ("streams", "devices", "connections")},
            },
        )

    with httpx.Client(
        base_url="http://fixture", transport=httpx.MockTransport(route)
    ) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            remove_recorded_entity(client, ENTITY)
        assert error.value.response.status_code == status
