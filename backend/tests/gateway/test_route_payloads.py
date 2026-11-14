"""Payloads of routes whose logic moved from routers into services."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from off_key_core.db.models import MonitoringService

from tests.support.gateway import gateway_app, member


def client(session):
    return TestClient(gateway_app(member(), session=session))


def service_session(services):
    session = AsyncMock()

    async def get(model, identifier, **_):
        assert model is MonitoringService
        return services.get(identifier)

    session.get.side_effect = get
    return session


def monitor(state):
    return SimpleNamespace(operational_status={"pipeline_state": state})


def test_pipeline_state_returns_the_stored_state_or_a_404():
    session = service_session({"m1": monitor({"nodes": 3}), "m2": monitor(None)})
    with client(session) as http:
        assert http.get("/v1/monitors/m1/pipeline/state").json() == {"nodes": 3}
        assert http.get("/v1/monitors/m2/pipeline/state").json() is None
        missing = http.get("/v1/monitors/unknown/pipeline/state")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Monitoring service not found"}


def test_workspace_reports_the_selected_service_state_and_tolerates_unknowns():
    session = service_session({})
    record = MonitoringService(
        id="m1",
        container_name="workload",
        mqtt_topic=["telemetry/fixture/temperature"],
        status=True,
        operational_status={"pipeline_state": {"nodes": 3}},
    )
    session.scalars.return_value = SimpleNamespace(all=lambda: [record])
    session.scalar.return_value = None  # nothing saved yet: no catalogue readings
    with client(session) as http:
        overview = "/v1/monitors/overview"
        selected = http.get(overview, params={"selected_monitor_id": "m1"})
        unknown = http.get(overview, params={"selected_monitor_id": "x"})
        none = http.get(overview)
    assert selected.json()["pipeline_state"] == {"nodes": 3}
    # The overview answers with the API's names; container details stay inside.
    assert selected.json()["selected_monitor_id"] == "m1"
    monitor = selected.json()["monitors"][0]
    assert "pipeline_state" not in monitor["operational_status"]
    assert monitor["reading_ids"] == []
    assert monitor["active"] is True
    assert "container_name" not in monitor
    assert unknown.json()["pipeline_state"] is None
    assert none.json()["pipeline_state"] is None
    assert session.scalars.await_count == 3
    session.get.assert_not_awaited()


def test_system_revisions_are_newest_first_with_isoformat_times():
    rows = [
        SimpleNamespace(
            revision=revision,
            updated_at=datetime(2026, 10, revision, tzinfo=UTC),
            updated_by="admin@example.com",
        )
        for revision in (2, 1)
    ]
    session = AsyncMock()
    session.scalars.return_value = rows
    with client(session) as http:
        response = http.get("/v1/catalogue/revisions")
    assert response.json() == [
        {
            "revision": 2,
            "updated_at": "2026-10-02T00:00:00+00:00",
            "updated_by": "admin@example.com",
        },
        {
            "revision": 1,
            "updated_at": "2026-10-01T00:00:00+00:00",
            "updated_by": "admin@example.com",
        },
    ]
    query = str(session.scalars.call_args.args[0])
    assert "ORDER BY system_revisions.revision DESC" in query
    assert "LIMIT" in query


def test_recording_preview_answers_every_count_not_only_the_renamed_fields():
    """The app reads affected_monitors before it saves a recording change."""
    from off_key_api_gateway.providers import get_system_service
    from off_key_core.schemas.system_collection import SystemCollectionPreview

    preview = SystemCollectionPreview(
        revision=4,
        collection_revision=5,
        selected_readings=1,
        sampled_rows_per_day_ceiling=86400,
        original_rate_readings=0,
        affected_monitors=[{"id": "m1"}],
        changed_readings=1,
        starting_readings=1,
        bindings={"r1": {"connection_id": "b1", "policy": {"mode": "off"}}},
    )
    system = SimpleNamespace(preview_collection=AsyncMock(return_value=preview))
    app = gateway_app(member("admin"), overrides={get_system_service: lambda: system})
    with TestClient(app) as http:
        response = http.post(
            "/v1/recording/preview",
            json={
                "expected_revision": 4,
                "expected_collection_revision": 5,
                "rule_changes": [
                    {
                        "scope": {"kind": "broker", "broker_id": "b1"},
                        "policy": {"mode": "sample", "interval_seconds": 1},
                    }
                ],
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["affected_monitors"] == [{"id": "m1"}]
    assert body["sampled_rows_per_day_ceiling"] == 86400
    assert body["starting_readings"] == 1
    assert body["bindings"]["r1"]["broker_id"] == "b1"
