"""RADAR turns consecutive heartbeats into a bounded lifecycle timeline."""

from datetime import UTC, datetime

from off_key_mqtt_radar.run_events import RunEventRecorder


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def status(stage, **values):
    return {"stage": stage, **values}


def kinds(recorder):
    return [(event["kind"], event["stage"]) for event in recorder.pending()]


def test_records_start_then_each_stage_with_the_time_spent_before_it():
    clock = Clock()
    recorder = RunEventRecorder(clock=clock)
    started = datetime(2026, 11, 3, 10, tzinfo=UTC)

    recorder.observe(status("waiting_for_data"), started_at=started)
    recorder.observe(status("waiting_for_data"))
    clock.now += 30
    recorder.observe(
        status("collecting_training", progress={"current": 5, "target": 10})
    )
    clock.now += 600.04
    recorder.observe(
        status("operational", processed_message_count=1570),
        {
            "strategy": "adaptive_stream",
            "threshold": 0.42,
            "pipeline_state": {
                "batch_training": {"state": "frozen", "training_samples": 1200},
                "nodes": {"model": {"state": "ready"}},
            },
        },
    )

    events = recorder.pending()
    assert kinds(recorder) == [
        ("runtime_started", "waiting_for_data"),
        ("stage_changed", "waiting_for_data"),
        ("stage_changed", "collecting_training"),
        ("stage_changed", "operational"),
    ]
    assert events[0]["occurred_at"] == started
    assert events[0]["detail"]["restored_from_checkpoint"] is False
    assert events[2]["detail"]["previous_stage_seconds"] == 30.0
    assert events[2]["detail"]["progress"] == {"current": 5, "target": 10}
    operational = events[3]["detail"]
    assert operational["from"] == "collecting_training"
    assert operational["previous_stage_seconds"] == 600.0
    assert operational["threshold"] == 0.42
    assert operational["batch_training"]["training_samples"] == 1200
    assert "failing_nodes" not in operational


def test_a_changed_degradation_reason_is_news_but_progress_is_not():
    recorder = RunEventRecorder(clock=Clock())
    recorder.observe(status("collecting_training", detail="1 of 10"))
    recorder.observe(status("collecting_training", detail="2 of 10"))
    recorder.observe(status("degraded", detail="Stale monitored inputs: a"))
    recorder.observe(status("degraded", detail="Stale monitored inputs: a"))
    recorder.observe(status("degraded", detail="Inference stalled"))

    assert kinds(recorder)[1:] == [
        ("stage_changed", "collecting_training"),
        ("stage_changed", "degraded"),
        ("stage_changed", "degraded"),
    ]
    assert "previous_stage_seconds" not in recorder.pending()[-1]["detail"]


def test_names_failing_nodes_on_a_transition():
    recorder = RunEventRecorder(clock=Clock())
    recorder.observe(
        status("degraded", detail="RADAR runtime is degraded"),
        {
            "pipeline_state": {
                "nodes": {
                    "scale": {"state": "failed", "error": "non-finite input"},
                    "model": {"state": "ready"},
                }
            }
        },
    )
    assert recorder.pending()[-1]["detail"]["failing_nodes"] == {
        "scale": {"state": "failed", "error": "non-finite input", "rejections": {}}
    }


def test_coverage_losses_after_start_are_reported_at_most_hourly():
    clock = Clock()
    recorder = RunEventRecorder(clock=clock)
    coverage = {"dropped_message_count": 4, "possible_gap_count": 1}
    # A restored checkpoint carries earlier losses; they are not news.
    recorder.observe(status("operational", coverage=coverage))
    recorder.observe(status("operational", coverage=coverage))
    recorder.observe(
        status(
            "operational",
            coverage={
                "dropped_message_count": 6,
                "possible_gap_count": 1,
                "last_gap_reason": "queue_full",
            },
        )
    )
    clock.now += 60
    recorder.observe(status("operational", coverage={"dropped_message_count": 9}))
    clock.now += 3600
    recorder.observe(
        status(
            "operational",
            coverage={"dropped_message_count": 10, "possible_gap_count": 2},
        )
    )

    gaps = [event for event in recorder.pending() if event["kind"] == "coverage_gap"]
    assert [gap["detail"]["new_losses"] for gap in gaps] == [2, 5]
    assert gaps[0]["detail"]["last_gap_reason"] == "queue_full"


def test_keeps_the_newest_events_and_counts_the_ones_it_dropped():
    recorder = RunEventRecorder(clock=Clock(), max_pending=3)
    for stage in ("starting", "waiting_for_data", "training", "operational"):
        recorder.observe(status(stage))

    events = recorder.pending()
    assert [event["stage"] for event in events] == [
        "waiting_for_data",
        "training",
        "operational",
    ]
    # Each event that displaced an older one says how many are gone so far.
    assert [event["detail"].get("events_dropped") for event in events] == [
        None,
        1,
        2,
    ]


def test_acknowledged_events_leave_and_drain_hands_over_the_rest():
    recorder = RunEventRecorder(clock=Clock())
    recorder.observe(status("starting"))
    sent = recorder.pending()
    recorder.observe(status("waiting_for_data"))
    recorder.acknowledge(len(sent))

    assert kinds(recorder) == [("stage_changed", "waiting_for_data")]
    assert [event["stage"] for event in recorder.drain()] == ["waiting_for_data"]
    assert recorder.pending() == []


def test_ignores_a_missing_status():
    recorder = RunEventRecorder(clock=Clock())
    recorder.observe(None)
    assert recorder.pending() == []
