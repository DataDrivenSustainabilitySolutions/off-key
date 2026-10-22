"""One truth table for which detector results count as inference."""

from datetime import UTC, datetime

import pytest
from off_key_mqtt_radar.activity import ActivityTracker
from off_key_mqtt_radar.models import AnomalyResult
from off_key_mqtt_radar.result_records import ResultProjector

STATIC = "static_conformal"
ADAPTIVE = "adaptive_stream"
# context, strategy context present, inference
TRUTH_TABLE = [
    (None, None, False),
    ({}, None, False),
    ({STATIC: {"phase": "ready"}}, STATIC, True),
    ({STATIC: {"phase": "collecting"}}, STATIC, False),
    ({STATIC: {"phase": "calibrating"}}, STATIC, False),
    ({STATIC: {}}, STATIC, False),
    ({ADAPTIVE: {"phase": "operational"}}, ADAPTIVE, True),
    ({ADAPTIVE: {"phase": "warming"}}, ADAPTIVE, False),
    ({ADAPTIVE: {"phase": "ready"}}, ADAPTIVE, False),
    ({ADAPTIVE: ["operational"]}, None, False),
    ({STATIC: {"phase": "operational"}}, STATIC, False),
    ({"score_window": {"tail_pvalue": 0.5}}, None, False),
]
VALUE_TYPES = {
    STATIC: "conformal_pvalue",
    ADAPTIVE: "anomaly_score",
    None: "tail_pvalue",
}


def _result(context):
    return AnomalyResult(
        anomaly_score=0.25,
        is_anomaly=False,
        severity="low",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        model_info={},
        raw_data={},
        topic="telemetry/c1/L1",
        charger_id="c1",
        context=context,
    )


@pytest.mark.parametrize("context,strategy,inference", TRUTH_TABLE)
def test_every_consumer_agrees_on_inference(context, strategy, inference):
    result = _result(context)
    tracker = ActivityTracker(set())
    tracker.record_result(result)
    (record,), _ = ResultProjector()._build_records([result])

    assert result.should_persist is inference
    assert (tracker.snapshot()["last_inference_at"] is not None) is inference
    assert record["value_type"] == VALUE_TYPES[strategy]


def test_anomalies_persist_whatever_their_phase():
    result = _result({STATIC: {"phase": "collecting"}})
    result.is_anomaly = True

    assert result.should_persist
