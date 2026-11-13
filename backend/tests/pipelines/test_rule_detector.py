"""The rule detector: one feature's value is the score, with no training."""

import math
import pickle

import pytest
from off_key_core.models import ADAPTIVE_MODELS_BY_TYPE, validate_adaptive_model_params
from off_key_core.models.adaptive import CATALOG, RULE_DETECTORS, detector_component
from off_key_core.models.pipelines import (
    compile_pipeline,
    derive_monitoring_config,
    pipeline_components,
    validate_pipeline,
)
from off_key_core.schemas.pipeline_versions import (
    RULE_DETECTOR,
    component_learning,
    streams,
)
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.mixed_detector import MixedDetectionService
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources
from off_key_mqtt_radar.preflight import preflight
from off_key_mqtt_radar.rules import FeatureScore, resolve_rule_detector
from off_key_tactic_middleware.models.catalog import available_models

from tests.support.boundary_pipeline import MAD
from tests.support.fused_pipeline import bound, reading
from tests.support.rule_pipeline import CALIBRATION, TRAINING, rule_definition

pytestmark = pytest.mark.radar_integration

ACI = {"calibration": "calibrate.aci", "calibration_params": {"alpha": 0.1}}
BOUNDARY = {**ACI, "policy": "policy.exceedance"}


def issues(definition):
    return [
        (item.code, item.node_id, item.message)
        for item in validate_pipeline(definition).issues
        if item.severity == "error"
    ]


def wave(index):
    return reading(math.sin(index / 5), math.cos(index / 7))


def gap(index):
    return abs(math.sin(index / 5) - math.cos(index / 7))


def feed(service, start, stop):
    results = []
    for index in range(start, stop):
        results.append(service.process_data_point(wave(index)))
        service.wait_for_background()
    return results


def phases(results):
    """Each phase the results went through, with how many observations it took."""
    names = [item.context["adaptive_stream"]["phase"] for item in results]
    return [(name, names.count(name)) for name in dict.fromkeys(names)]


def outcomes(results):
    return [
        (
            item.anomaly_score,
            item.context["adaptive_stream"]["threshold"],
            item.is_anomaly,
        )
        for item in results
    ]


def test_the_catalog_lists_a_detector_that_learns_nothing():
    component = {item.id: item for item in pipeline_components()}[RULE_DETECTOR]

    assert component.kind == "detector" and component.label == "Rule detector"
    assert component.learning == "none"
    assert (component.input_type, component.output_type) == ("features", "scores")
    assert component.fields == []
    assert "no training" in component.description
    # It is RADAR's own: its identifier is its model type, and Aberrant has none.
    assert detector_component(RULE_DETECTOR) == RULE_DETECTOR
    assert RULE_DETECTOR not in CATALOG["models"]
    assert ADAPTIVE_MODELS_BY_TYPE[RULE_DETECTOR] is RULE_DETECTORS[RULE_DETECTOR]
    assert component_learning(RULE_DETECTOR) == "none" and streams(RULE_DETECTOR)
    assert streams(MAD) and not streams("detector:pyod_knn")


def test_a_rule_detector_has_no_settings():
    assert validate_adaptive_model_params(RULE_DETECTOR, None) == {}
    with pytest.raises(ValueError, match="limit"):
        validate_adaptive_model_params(RULE_DETECTOR, {"limit": 5})
    [(code, node, _)] = issues(rule_definition(rule_params={"limit": 5}))
    assert (code, node) == ("parameters", "rule")


def test_a_rule_detector_scores_exactly_one_feature():
    assert issues(rule_definition()) == []
    # Reading b stays beside the result, so two features arrive.
    [(code, node, message)] = issues(rule_definition(expression="abs(a)"))
    assert (code, node) == ("model_features", "rule")
    assert "1 to 1 features" in message


@pytest.mark.parametrize("step", ["adaptive.standard_scaler", "static.standard_scaler"])
def test_a_rule_detector_reads_only_steps_that_do_not_learn(step):
    [(code, node, message)] = issues(rule_definition(before=step))

    assert (code, node) == ("learning", "before")
    assert message.endswith(
        "can't feed Rule detector: the detector follows a rule and reads only "
        "steps that do not learn."
    )


def test_a_rule_detector_alarms_on_its_score_and_not_on_p_values():
    assert issues(rule_definition()) == []
    assert issues(rule_definition(**BOUNDARY)) == []
    assert issues(rule_definition(("mad",))) == []
    assert issues(rule_definition(("knn",))) == []
    assert issues(rule_definition(("knn", "mad"), **BOUNDARY)) == []
    for others in [(), ("knn",)]:
        [(code, node, message)] = issues(
            rule_definition(others, policy="policy.martingale")
        )
        assert (code, node) == ("calibration", "policy")
        assert message == (
            "The conformal alarm policy does not run on a rule detector. Use the "
            "calibrated score threshold."
        )


def test_a_score_that_never_changes_is_pointed_out():
    report = validate_pipeline(rule_definition(expression="0 * (a + b)"))

    assert report.valid
    [warning] = [item for item in report.issues if item.code == "constant_feature"]
    assert warning.node_id == "rule"
    assert warning.message == (
        "gap is always 0, so Rule detector gives every observation the same score."
    )


def test_a_design_of_rule_detectors_runs_on_the_stream():
    alone = rule_definition()

    assert alone.lane == "adaptive_stream"
    # It is still written as the schema 1 design it can be, and reads back the same.
    written = alone.model_dump(mode="json")
    assert (written["schema_version"], written["strategy"]) == (1, "adaptive_stream")
    assert (
        compile_pipeline(PipelineDefinition.model_validate(written)).fingerprint
        == compile_pipeline(alone).fingerprint
    )
    monitoring = derive_monitoring_config(alone)
    assert isinstance(monitoring, AdaptiveStreamConfig)
    assert (monitoring.model_type, monitoring.model_params) == (RULE_DETECTOR, {})
    # Beside a detector that learns continuously it shares that detector's lane;
    # beside one fitted once the design has none.
    assert rule_definition(("mad",)).lane == "adaptive_stream"
    assert rule_definition(("knn",)).lane is None
    assert isinstance(
        derive_monitoring_config(rule_definition(("knn",))), AdaptiveStreamConfig
    )


def test_the_score_is_the_value_of_the_feature():
    model = FeatureScore("gap")

    assert model.score_one({"gap": -2.5}) == -2.5
    model.learn_one({"gap": 40.0})
    assert model.score_one({"gap": 0.0}) == 0.0
    assert pickle.loads(pickle.dumps(model)).score_one({"gap": 3.0}) == 3.0
    with pytest.raises(ValueError, match="key"):
        FeatureScore("")
    resolved = resolve_rule_detector({"id": RULE_DETECTOR, "params": {"key": "gap"}})
    assert (
        resolved.capabilities.as_dict()
        == (RULE_DETECTORS[RULE_DETECTOR]["default_capabilities"])
    )
    assert resolved.build().key == "gap"
    other = resolve_rule_detector({"id": RULE_DETECTOR, "params": {"key": "flag"}})
    assert other.fingerprint != resolved.fingerprint


def test_a_rule_alone_calibrates_from_its_first_observation():
    config = bound(rule_definition())
    assert detector_service_class(config) is AdaptiveStreamDetectionService
    service = AdaptiveStreamDetectionService(config)

    assert service.state is AdaptiveStreamState.CALIBRATING
    results = feed(service, 0, CALIBRATION + 30)

    assert phases(results) == [("calibration", CALIBRATION), ("operational", 30)]
    scores = [item.anomaly_score for item in results]
    assert scores == pytest.approx([gap(index) for index in range(len(results))])
    assert results[0].processed_features == {"gap": scores[0]}
    # The threshold is the largest calibration score, and only a score above it alarms.
    threshold = max(scores[:CALIBRATION])
    assert service.threshold == threshold
    assert [item.is_anomaly for item in results[CALIBRATION:]] == [
        score > threshold for score in scores[CALIBRATION:]
    ]
    assert service.get_pipeline_state()["adaptive_learning"] == {
        "state": "operational",
        "model_updates": CALIBRATION + 30,
        "warmup_updates": 0,
        "warmup_required": 0,
        "ready": True,
        "reason": None,
    }
    info = service.get_model_info()
    assert (info["model_type"], info["catalog_id"]) == (RULE_DETECTOR, RULE_DETECTOR)
    assert info["capabilities"]["state"] == "stateless"


def test_a_hard_limit_alarms_while_its_flag_is_set():
    definition = rule_definition(
        expression="if(a > 5 or b > 5, 1, 0)", calibration_window=3
    )
    service = AdaptiveStreamDetectionService(bound(definition))
    values = [1.0, 2.0, 3.0, 4.0, 9.0, 5.0, 5.5, 0.0]

    results = [service.process_data_point(reading(a, 0.0)) for a in values]

    assert [item.anomaly_score for item in results] == [0, 0, 0, 0, 1, 0, 1, 0]
    assert [item.is_anomaly for item in results] == [
        False,
        False,
        False,
        False,
        True,
        False,
        True,
        False,
    ]
    assert service.threshold == 0.0


@pytest.mark.parametrize(
    ("others", "settings", "service_class"),
    [
        (("mad",), {}, AdaptiveStreamDetectionService),
        (("knn",), {}, MixedDetectionService),
        (("knn", "mad"), BOUNDARY, BoundaryDetectionService),
    ],
)
def test_a_rule_runs_beside_detectors_that_learn(others, settings, service_class):
    config = bound(rule_definition(others, **settings))
    assert detector_service_class(config) is service_class
    service = service_class(config)
    try:
        results = feed(service, 0, TRAINING + CALIBRATION + 20)

        # The other detectors learn first, so the run warms up as they need.
        assert phases(results) == [
            ("warmup", TRAINING),
            ("calibration", CALIBRATION),
            ("operational", 20),
        ]
        last = results[-1].context["adaptive_stream"]
        scored = {item["detector_id"]: item["score"] for item in last["detectors"]}
        assert set(scored) == {"rule", *others}
        assert scored["rule"] == pytest.approx(gap(len(results) - 1))
        assert estimate_resources(ExecutionPlan(config.pipeline), 512)
        assert preflight(config.pipeline)["ok"]
    finally:
        service.shutdown()


def test_a_rule_under_an_adapting_boundary_starts_at_once():
    config = bound(rule_definition(**BOUNDARY))
    assert detector_service_class(config) is BoundaryDetectionService
    service = BoundaryDetectionService(config)
    try:
        results = feed(service, 0, CALIBRATION + 40)

        assert phases(results) == [("calibration", CALIBRATION), ("operational", 40)]
        assert service.boundary.started
        assert [item.anomaly_score for item in results[CALIBRATION:]] == pytest.approx(
            [gap(index) for index in range(CALIBRATION, CALIBRATION + 40)]
        )
        assert preflight(config.pipeline)["ok"]
    finally:
        service.shutdown()


@pytest.mark.parametrize(
    ("others", "settings", "service_class"),
    [
        ((), {}, AdaptiveStreamDetectionService),
        (("mad",), {}, AdaptiveStreamDetectionService),
        (("knn",), {}, MixedDetectionService),
        ((), BOUNDARY, BoundaryDetectionService),
    ],
)
@pytest.mark.parametrize("stop", [5, CALIBRATION, TRAINING + CALIBRATION + 3])
def test_a_checkpoint_continues_exactly_where_it_left_off(
    others, settings, service_class, stop
):
    config = bound(rule_definition(others, **settings))
    original = service_class(config)
    try:
        feed(original, 0, stop)
        restored = service_class.from_checkpoint_data(
            pickle.loads(pickle.dumps(original.export_checkpoint())), config
        )
        try:
            original.wait_for_background()
            restored.wait_for_background()
            assert restored.state is original.state
            expected = outcomes(feed(original, stop, stop + 60))
            assert outcomes(feed(restored, stop, stop + 60)) == expected
        finally:
            restored.shutdown()
    finally:
        original.shutdown()


def test_a_detector_behind_a_prepare_step_reads_only_that_step():
    # Another detector reads the input itself, so the input crosses into the
    # learned stage; the detector behind the formula reads the formula alone.
    definition = rule_definition(("mad",), rule=MAD, rule_params={"window_size": 10})
    service = AdaptiveStreamDetectionService(bound(definition))

    by_detector = dict(zip(service.online_ids, service.pipelines, strict=True))
    assert [node.id for node in by_detector["rule"].nodes] == ["gap"]
    assert [node.id for node in by_detector["mad"].nodes] == [
        "input",
        "only_b",
        "scale_b",
    ]
    results = feed(service, 0, TRAINING + CALIBRATION + 5)
    assert phases(results)[-1] == ("operational", 5)


def test_the_setup_form_does_not_offer_a_rule_detector():
    # A rule needs a step before it to state it, which only the composer has.
    # The form lists what a release's field discovery serves, and the rollback
    # rehearsal expects settings for every model in it.
    offered = {item["model_type"]: item["fields"] for item in available_models()}

    assert RULE_DETECTOR not in offered
    assert set(offered) >= set(ADAPTIVE_MODELS_BY_TYPE) - set(RULE_DETECTORS)
    assert all(offered.values())
