"""RADAR's reporting cadence must stay inside TACTIC's freshness windows."""

from datetime import UTC, datetime, timedelta

from off_key_mqtt_radar.config.config import (
    PIPELINE_HEARTBEAT_INTERVAL_CAP,
    MQTTRadarConfig,
)
from off_key_tactic_middleware.services.orchestration.radar_status import (
    PIPELINE_ACTIVATION_HEARTBEAT_MAX_AGE_SECONDS,
    RUNTIME_STATUS_STALE_AFTER_SECONDS,
    heartbeat_age_seconds,
)


def test_radar_reports_well_inside_tactic_freshness_windows():
    default_interval = MQTTRadarConfig.model_fields["health_check_interval"].default
    assert default_interval < RUNTIME_STATUS_STALE_AFTER_SECONDS
    assert (
        PIPELINE_HEARTBEAT_INTERVAL_CAP < PIPELINE_ACTIVATION_HEARTBEAT_MAX_AGE_SECONDS
    )


def test_heartbeat_age_is_measured_from_the_persisted_timestamp():
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    assert heartbeat_age_seconds(now - timedelta(seconds=31), now) == 31.0
