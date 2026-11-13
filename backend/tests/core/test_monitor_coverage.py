"""A monitor names the catalogue readings it watches, not only MQTT filters."""

from off_key_core.db.models import MonitoringService
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    ReadingBinding,
    SystemCollectionDefinition,
)
from off_key_tactic_middleware.services.orchestration.radar_queries import (
    service_summary,
)

CATALOGUE = SystemCollectionDefinition(
    document=SystemDocument(),
    bindings={
        stream_id: ReadingBinding(
            entity_id=entity,
            telemetry_key=key,
            accepted_topic=f"telemetry/{entity}/{key}",
        )
        for stream_id, entity, key in (
            ("line-temperature", "line", "temperature"),
            ("line-pressure", "line", "pressure"),
            ("hall-temperature", "hall", "temperature"),
        )
    },
)


def test_concrete_topics_and_filters_resolve_to_catalogue_readings():
    assert CATALOGUE.watched_by(["telemetry/line/temperature"]) == ["line-temperature"]
    assert CATALOGUE.watched_by(["telemetry/line/+"]) == [
        "line-pressure",
        "line-temperature",
    ]
    assert CATALOGUE.watched_by(["telemetry/+/temperature", "telemetry/#"]) == [
        "hall-temperature",
        "line-pressure",
        "line-temperature",
    ]


def test_unknown_missing_and_malformed_topics_watch_nothing():
    assert CATALOGUE.watched_by(["telemetry/removed/temperature"]) == []
    assert CATALOGUE.watched_by(None) == []
    assert CATALOGUE.watched_by(["telemetry/#/bad", ""]) == []


def test_every_monitor_summary_lists_its_readings():
    service = MonitoringService(
        id="m1",
        container_name="workload",
        mqtt_topic=["telemetry/line/temperature", "telemetry/line/pressure"],
        status=True,
    )
    summary = service_summary(service, CATALOGUE)
    assert summary["stream_ids"] == ["line-pressure", "line-temperature"]
    # The recorded topics name internal identities and stay inside.
    assert "mqtt_topics" not in summary
    assert summary["shadow"] is False


def test_a_monitor_summary_says_when_the_monitor_runs_in_shadow():
    service = MonitoringService(
        id="m1",
        container_name="workload",
        mqtt_topic=["telemetry/line/temperature"],
        status=True,
        launch_config={"shadow": True},
    )
    assert service_summary(service, CATALOGUE)["shadow"] is True


def test_monitor_activity_names_its_inputs_by_reading():
    service = MonitoringService(
        id="m1",
        container_name="workload",
        mqtt_topic=["telemetry/line/temperature", "telemetry/line/pressure"],
        status=True,
        operational_stage="degraded",
        operational_status={
            "stage": "degraded",
            "activity": {
                "freshness_seconds": 30,
                "missing_sensors": ["pressure"],
                "stale_sensors": ["temperature", "removed"],
            },
        },
        launch_config={
            "pipeline": {
                "bindings": [
                    {"input_key": "temperature", "reading_id": "line-temperature"},
                    {"input_key": "pressure", "reading_id": "line-pressure"},
                ]
            }
        },
    )
    activity = service_summary(service, CATALOGUE)["operational_status"]["activity"]
    assert activity["missing_reading_ids"] == ["line-pressure"]
    # A key no binding names any more is left out rather than shown.
    assert activity["stale_reading_ids"] == ["line-temperature"]
    assert "missing_sensors" not in activity and "stale_sensors" not in activity
