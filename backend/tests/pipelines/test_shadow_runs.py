"""A shadow run: it learns and scores as a live one and raises no alarm."""

import math
import pickle

import pytest
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.result_records import ResultProjector

from tests.support.conformal_run import (
    ControlledExecutor,
    FakeConformalDetector,
    tracker,
)
from tests.support.fused_pipeline import KEYS, bound, reading
from tests.support.rule_pipeline import CALIBRATION, rule_definition

pytestmark = pytest.mark.radar_integration

# A flag that is 1 where reading a is above 5.
LIMIT = "if(a > 5, 1, 0) + 0 * b"
BOUNDARY = {
    "calibration": "calibrate.aci",
    "calibration_params": {"alpha": 0.1},
    "policy": "policy.exceedance",
}
RAISED, KEPT_BACK, QUIET = (True, True, False), (False, False, True), (False,) * 3


def in_shadow(config: AnomalyDetectionConfig) -> AnomalyDetectionConfig:
    return config.model_copy(update={"shadow": True})


def outcome(result):
    context = result.context["adaptive_stream"]
    return (
        result.is_anomaly,
        context["alarm_fired"],
        context.get("alarm_muted", False),
    )


def static_outcome(result):
    context = result.context["static_conformal"]
    return (result.is_anomaly, context["alarm_fired"], context["alarm_muted"])


def test_shadow_is_no_part_of_what_a_run_learns():
    live = bound(rule_definition(expression=LIMIT, calibration_window=3))
    shadow = in_shadow(live)

    assert not live.shadow and shadow.shadow
    # The same design on the same readings: what is executed is the same.
    assert shadow.pipeline == live.pipeline


def test_a_threshold_run_in_shadow_scores_alike_and_keeps_every_alarm_back():
    live = bound(rule_definition(expression=LIMIT, calibration_window=3))
    service = AdaptiveStreamDetectionService(in_shadow(live))
    reference = AdaptiveStreamDetectionService(live)
    values = [1] * 10 + [9, 1, 9, 9]

    results = [service.process_data_point(reading(a, 0)) for a in values]
    expected = [reference.process_data_point(reading(a, 0)) for a in values]

    assert [item.anomaly_score for item in results] == [
        item.anomaly_score for item in expected
    ]
    assert [outcome(item) for item in expected[-4:]] == [RAISED, QUIET, RAISED, RAISED]
    assert [outcome(item) for item in results[-4:]] == [
        KEPT_BACK,
        QUIET,
        KEPT_BACK,
        KEPT_BACK,
    ]
    assert (service.anomaly_count, reference.anomaly_count) == (0, 3)
    assert {item.severity for item in results} == {"low"}


def test_an_adapting_boundary_in_shadow_goes_live_with_what_it_learned():
    live = bound(rule_definition(**BOUNDARY))
    service = BoundaryDetectionService(in_shadow(live))
    reference = BoundaryDetectionService(live)
    values = [math.sin(index / 5) for index in range(CALIBRATION)] + [0.5, 51, 90, 0.5]

    results = [service.process_data_point(reading(a, 0)) for a in values]
    expected = [reference.process_data_point(reading(a, 0)) for a in values]

    assert [
        (item.anomaly_score, item.context["adaptive_stream"]["threshold"])
        for item in results
    ] == [
        (item.anomaly_score, item.context["adaptive_stream"]["threshold"])
        for item in expected
    ]
    assert [outcome(item) for item in expected[-4:]] == [QUIET, RAISED, RAISED, QUIET]
    assert [outcome(item) for item in results[-4:]] == [
        QUIET,
        KEPT_BACK,
        KEPT_BACK,
        QUIET,
    ]
    assert (service.anomaly_count, reference.anomaly_count) == (0, 2)
    # Shadow belongs to the run's configuration, not to what it learned: the
    # same checkpoint raises alarms under a live configuration.
    checkpoint = pickle.dumps(service.export_checkpoint())
    still, gone_live = (
        BoundaryDetectionService.from_checkpoint_data(pickle.loads(checkpoint), config)
        for config in (in_shadow(live), live)
    )
    assert outcome(still.process_data_point(reading(200, 0))) == KEPT_BACK
    assert outcome(gone_live.process_data_point(reading(200, 0))) == RAISED


def test_a_conformal_run_in_shadow_keeps_every_crossing_back():
    design = rule_definition(
        rule="detector:pyod_iforest", policy="policy.martingale"
    ).model_dump(mode="json")
    design["settings"].update(training_window_size=20, calibration_window_size=5)
    config = in_shadow(bound(PipelineDefinition.model_validate(design)))
    service = StaticConformalDetectionService(config)
    service._training_executor = ControlledExecutor()
    fitted = FakeConformalDetector()
    try:
        for index in range(25):
            service.process_data_point(reading(math.sin(index), 0))
        service._training_executor.future.set_result((fitted, tracker()))
        results = []
        # The statistic crosses its threshold, falls back and crosses again.
        for p_value in [1.0, 1e-6, 1.0, 1.0, 1e-6]:
            fitted.p_value = p_value
            results.append(service.process_data_point(reading(1, 0)))

        assert [static_outcome(item) for item in results] == [
            QUIET,
            KEPT_BACK,
            QUIET,
            QUIET,
            KEPT_BACK,
        ]
        assert service.anomaly_count == 0
        assert {item.severity for item in results} == {"low"}
    finally:
        service.shutdown()


def test_the_evidence_of_a_shadow_run_keeps_its_alarms_and_stores_no_anomaly():
    live = bound(rule_definition(expression=LIMIT, calibration_window=3))
    service = AdaptiveStreamDetectionService(in_shadow(live))
    results = [service.process_data_point(reading(a, 0)) for a in (1, 2, 3, 9)]
    stamp = "2026-08-06T10:00:00Z"
    for item in results:
        item.context["alignment"] = {
            "aligned_vector": True,
            "required_sensors": list(KEYS.values()),
            "input_timestamps": dict.fromkeys(KEYS.values(), stamp),
        }

    kept = ResultProjector(service_id="monitor").prepare(results[-1])

    assert [(row["alarm"], row["muted"]) for row in kept.evidence] == [(False, True)]
    assert kept.anomalies == []
