"""Health describes current useful activity, independently of cumulative counts."""

from datetime import UTC, datetime
from types import SimpleNamespace

from off_key_mqtt_radar.activity import ActivityTracker, evaluate_activity
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.models import AnomalyResult, MQTTMessage


def _result(phase="ready", **context):
    return AnomalyResult(
        anomaly_score=0.5,
        is_anomaly=False,
        severity="low",
        timestamp=datetime.now(UTC),
        model_info={},
        raw_data={"a": 1.0},
        context={"static_conformal": {"phase": phase}, **context},
    )


def _input(tracker, sensor, clock):
    tracker.record_input(
        sensor,
        MQTTMessage(
            topic=f"telemetry/entity/{sensor}",
            payload=b'{"value":1}',
            timestamp=datetime.now(UTC),
            received_monotonic=clock,
        ),
    )


def _health(tracker, *, state="ready", processed_count=10, database_health=None):
    monitor = HealthMonitor(sensor_freshness_seconds=5.0)
    monitor.start_time = datetime.now()
    monitor.set_components(
        detector=SimpleNamespace(
            get_health_info=lambda: {
                "state": "healthy",
                "primary_service_stats": {
                    "strategy": "static_baseline",
                    "state": state,
                    "training_collected_samples": 3,
                    "training_window_size": 10,
                },
            }
        ),
        message_processor=SimpleNamespace(
            get_metrics=lambda: {
                "message_count": processed_count,
                "processed_message_count": processed_count,
                "activity": tracker.snapshot(),
            }
        ),
        database_writer=SimpleNamespace(get_health_status=lambda: database_health)
        if database_health
        else None,
    )
    return monitor.get_health_status()


def test_receipt_clocks_include_time_spent_waiting_in_queue():
    tracker = ActivityTracker({"a"}, clock=lambda: 100.0)
    _input(tracker, "a", 90.0)
    activity = evaluate_activity(
        tracker.snapshot(),
        freshness_seconds=5.0,
        inference_expected=False,
        database_health={},
    )
    assert activity.stale_sensors == ["a"]
    assert activity.inputs_stalled


def test_missing_or_silent_inputs_degrade_health_without_a_new_callback():
    clock = [100.0]
    tracker = ActivityTracker({"a", "b"}, clock=lambda: clock[0])
    for sensor in ("a", "b"):
        _input(tracker, sensor, clock[0])
    tracker.record_result(_result())
    assert _health(tracker).status == "healthy"
    clock[0] = 106.0
    status = _health(tracker)
    assert status.status == "degraded"
    operational = status.metrics["operational_status"]
    assert operational["stage"] == "degraded"
    assert operational["activity"]["stale_sensors"] == ["a", "b"]
    assert operational["activity"]["inference_stalled"]
    assert not operational["is_stale"]
    # A still-publishing sensor cannot hide its stale peer.
    _input(tracker, "a", clock[0])
    assert _health(tracker).metrics["activity"]["stale_sensors"] == ["b"]
    _input(tracker, "b", clock[0])
    tracker.record_result(_result())
    assert _health(tracker).metrics["operational_status"]["stage"] == "operational"


def test_primary_fallback_does_not_advance_successful_inference():
    clock = [100.0]
    tracker = ActivityTracker({"a"}, clock=lambda: clock[0])
    _input(tracker, "a", clock[0])
    tracker.record_result(_result())
    initial = tracker.snapshot()
    clock[0] = 106.0
    _input(tracker, "a", clock[0])
    tracker.record_result(_result(fallback_reason="model failed"))
    current = tracker.snapshot()
    assert current["last_processed_at"] == initial["last_processed_at"]
    assert current["last_inference_at"] == initial["last_inference_at"]
    activity = _health(tracker).metrics["activity"]
    assert activity["inference_stalled"]
    assert not activity["inputs_stalled"]


def test_restored_counts_wait_for_real_runtime_inference():
    clock = [100.0]
    tracker = ActivityTracker({"a", "b"}, clock=lambda: clock[0])
    status = _health(tracker, processed_count=1200)
    assert status.metrics["operational_status"]["stage"] == "waiting_for_data"
    assert status.metrics["activity"]["missing_sensors"] == ["a", "b"]
    clock[0] = 106.0
    assert _health(tracker, processed_count=1200).status == "degraded"


def test_stale_input_overlay_preserves_training_progress():
    clock = [100.0]
    tracker = ActivityTracker({"a"}, clock=lambda: clock[0])
    _input(tracker, "a", clock[0])
    tracker.record_result(_result("collecting"))
    clock[0] = 106.0
    status = _health(tracker, state="collecting")
    operational = status.metrics["operational_status"]
    assert operational["stage"] == "degraded"
    assert operational["progress"] == {"current": 3, "target": 10}
    assert not operational["activity"]["inference_stalled"]


def test_old_successful_write_is_only_a_problem_when_evidence_is_pending():
    tracker = ActivityTracker({"a"}, clock=lambda: 100.0)
    _input(tracker, "a", 100.0)
    tracker.record_result(_result())
    database_health = {
        "status": "healthy",
        "last_persisted_at": "2026-01-01T00:00:00Z",
        "persistence_timeout_seconds": 10.0,
        "oldest_pending_age_seconds": None,
    }
    assert _health(tracker, database_health=database_health).status == "healthy"
    database_health["oldest_pending_age_seconds"] = 11.0
    status = _health(tracker, database_health=database_health)
    assert status.status == "degraded"
    assert status.metrics["activity"]["persistence_stalled"]
    assert "persisted" in status.metrics["operational_status"]["detail"]
