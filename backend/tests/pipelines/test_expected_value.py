"""Expected value: one feature fitted from the others, given as its residual."""

import math
import pickle

import numpy as np
import pytest
from aberrant.compose import GraphExecutionError
from aberrant.forecast import RLSRegressor
from off_key_core.models.pipelines import (
    compile_pipeline,
    pipeline_catalog,
    validate_pipeline,
)
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.batch import BatchFeatureGraph
from off_key_mqtt_radar.pipelines.expected import OnlineExpectedValue
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources

from tests.support.pipelines import chained, chained_execution

pytestmark = pytest.mark.radar_integration

SLOTS = ("current", "flow", "pressure", "temperature")
FAMILIES = {"static_baseline": "static", "adaptive_stream": "adaptive"}
STRATEGIES = sorted(FAMILIES)
LOAD = {"target": "current", "apply_to": ["flow", "pressure"]}


def _rows(count=60, gain=2.0):
    """A pump whose current follows flow and pressure; temperature goes its own way."""
    rng = np.random.default_rng(7)
    flow = rng.uniform(1, 5, count)
    pressure = rng.uniform(2, 3, count)
    return [
        {
            "current": gain * f - 0.5 * p + 4.0 + noise,
            "flow": f,
            "pressure": p,
            "temperature": t,
        }
        for f, p, t, noise in zip(
            flow,
            pressure,
            rng.normal(20, 1, count),
            rng.normal(0, 0.01, count),
            strict=True,
        )
    ]


ROWS = _rows()


def steps(strategy, params, after=()):
    return [("expect", f"{FAMILIES[strategy]}.expected_value", params), *after]


def design(strategy, params, slots=SLOTS, after=()):
    return chained(strategy, steps(strategy, params, after), slots)


def plan(strategy, params, after=()):
    return ExecutionPlan(
        chained_execution(strategy, steps(strategy, params, after), SLOTS)
    )


def issue(strategy, params, slots=SLOTS, after=(), node="expect"):
    result = validate_pipeline(design(strategy, params, slots, after))
    assert not result.valid
    found = next(item for item in result.issues if item.node_id == node)
    return found.code, found.message, found.parameter_path


def test_both_forms_are_offered_as_steps_that_learn():
    offered = {
        item.id: item
        for item in pipeline_catalog(authoring_enabled=True).components
        if item.id.endswith(".expected_value")
    }
    assert {key: item.learning for key, item in offered.items()} == {
        "static.expected_value": "batch",
        "adaptive.expected_value": "online",
    }
    fields = {
        key: [(field.name, field.required) for field in item.fields]
        for key, item in offered.items()
    }
    shared = [("apply_to", False), ("result", False), ("target", True), ("name", False)]
    assert fields == {
        "static.expected_value": shared,
        "adaptive.expected_value": [*shared, ("forgetting", False)],
    }


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_the_residual_replaces_what_it_is_expected_from_or_joins_it(strategy):
    def columns(params):
        return compile_pipeline(design(strategy, params)).features["expect"]

    alone = columns({"target": "current"})
    assert [(item.name, item.slots, item.raw, item.steps) for item in alone] == [
        ("current_residual", sorted(SLOTS), False, ["expect"])
    ]
    assert (alone[0].minimum, alone[0].maximum) == (None, None)
    beside = columns(LOAD)
    assert [(item.name, item.slots, item.raw) for item in beside] == [
        ("temperature", ["temperature"], True),
        ("current_residual", ["current", "flow", "pressure"], False),
    ]
    added = columns({**LOAD, "result": "add", "name": "load_gap"})
    assert [item.name for item in added] == [*SLOTS, "load_gap"]
    assert [item.raw for item in added] == [True, True, True, True, False]
    # A residual that replaces its target may take the target's name.
    renamed = columns({**LOAD, "name": "current"})
    assert [item.name for item in renamed] == ["temperature", "current"]


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_settings_at_their_defaults_leave_the_fingerprint_alone(strategy):
    def fingerprint(params):
        return compile_pipeline(design(strategy, params)).fingerprint

    plain = fingerprint({"target": "current"})
    spelled = {"target": "current", "apply_to": None, "result": "replace", "name": None}
    if strategy == "adaptive_stream":
        spelled["forgetting"] = 1.0
    assert fingerprint(spelled) == plain
    assert fingerprint({"target": "current", "name": "gap"}) != plain
    assert fingerprint({"target": "current", "result": "add"}) != plain


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize(
    ("params", "slots", "expected"),
    [
        (
            {"target": "voltage"},
            SLOTS,
            ("scope", "voltage is not available at this step.", ["target"]),
        ),
        (
            {"target": "current", "apply_to": ["voltage"]},
            SLOTS,
            ("scope", "voltage is not available at this step.", ["apply_to"]),
        ),
        (
            {"target": "current", "apply_to": ["current", "flow"]},
            SLOTS,
            (
                "scope",
                "current is the feature that is expected. Leave it out of "
                "Expected from.",
                ["apply_to"],
            ),
        ),
        (
            {"target": "current"},
            ("current",),
            (
                "scope",
                "Only current arrives here. An Expected value needs another "
                "feature to expect it from.",
                ["apply_to"],
            ),
        ),
        (
            {"target": "current", "apply_to": ["flow"], "name": "pressure"},
            SLOTS,
            ("scope", "pressure already exists. Choose another name.", ["name"]),
        ),
        (
            {"target": "current", "result": "add", "name": "flow"},
            SLOTS,
            ("scope", "flow already exists. Choose another name.", ["name"]),
        ),
        ({}, SLOTS, ("parameters", "Enter a value.", ["target"])),
    ],
)
def test_the_step_says_which_setting_cannot_apply(strategy, params, slots, expected):
    assert issue(strategy, params, slots) == expected


def test_only_the_continuous_fit_forgets():
    assert issue("adaptive_stream", {"target": "current", "forgetting": 0}) == (
        "parameters",
        "Input should be greater than 0",
        ["forgetting"],
    )
    assert issue("static_baseline", {"target": "current", "forgetting": 0.9}) == (
        "parameters",
        "Extra inputs are not permitted",
        ["forgetting"],
    )


def test_a_fit_on_training_data_needs_more_observations_than_coefficients():
    # The test designs train on 20 observations.
    slots = tuple(f"s{index}" for index in range(21))
    assert issue("static_baseline", {"target": "s0"}, slots) == (
        "feature_schema",
        "Expecting s0 from 20 features fits 21 coefficients and needs more "
        "training observations than that",
        None,
    )
    fewer = design("static_baseline", {"target": "s0"}, slots[:19])
    assert validate_pipeline(fewer).valid
    # The continuous fit waits for the observations it needs instead.
    assert validate_pipeline(design("adaptive_stream", {"target": "s0"}, slots)).valid


def test_the_step_learns_so_prepare_steps_come_first_and_the_detector_learns_alike():
    code, message, _ = issue(
        "static_baseline",
        {"target": "current"},
        after=[("smooth", "prepare.smooth", {})],
        node="smooth",
    )
    assert (code, message) == (
        "stage",
        "Smooth must come before Expected value: prepare steps run before "
        "anything learns.",
    )
    crossed = chained(
        "static_baseline",
        [("expect", "adaptive.expected_value", {"target": "current"})],
        SLOTS,
    )
    codes = {item.code for item in validate_pipeline(crossed).issues}
    assert "learning" in codes


def _matrix(names, rows):
    return np.array([[row[name] for name in names] for row in rows])


def test_the_fitted_step_gives_least_squares_residuals_from_the_training_fit():
    bound = plan("static_baseline", {**LOAD, "result": "add"})
    graph = BatchFeatureGraph(bound)
    names = bound.names(bound.source_id)
    rows = _matrix(names, ROWS)
    fitted = graph.fit_transform(rows[:40])
    later = graph.transform(rows[40:])
    assert bound.output_features == [*SLOTS, "current_residual"]
    # Everything the step was given goes on unchanged.
    np.testing.assert_array_equal(later[:, :4], rows[40:])
    design_matrix = np.column_stack(
        [_matrix(["flow", "pressure"], ROWS), np.ones(len(ROWS))]
    )
    target = _matrix(["current"], ROWS)[:, 0]
    weights = np.linalg.lstsq(design_matrix[:40], target[:40], rcond=None)[0]
    np.testing.assert_allclose(weights, [2.0, -0.5, 4.0], atol=0.05)
    residual = target - design_matrix @ weights
    np.testing.assert_allclose(fitted[:, 4], residual[:40], atol=1e-9)
    # Later observations are measured against the same fit.
    np.testing.assert_allclose(later[:, 4], residual[40:], atol=1e-9)
    assert abs(later[:, 4]).max() < 0.05
    restored = pickle.loads(pickle.dumps(graph))
    np.testing.assert_array_equal(restored.transform(rows[40:]), later)


def test_inputs_that_rest_or_repeat_each_other_still_fit():
    rows = [{**row, "pressure": 2.5, "temperature": row["flow"]} for row in _rows()]
    bound = plan("static_baseline", {"target": "current"})
    graph = BatchFeatureGraph(bound)
    names = bound.names(bound.source_id)
    fitted = graph.fit_transform(_matrix(names, rows[:40]))
    assert np.isfinite(fitted).all()
    # The constant input adds nothing and the two alike share the weight.
    single = np.column_stack([_matrix(["flow"], rows[:40]), np.ones(40)])
    target = _matrix(["current"], rows[:40])[:, 0]
    weights = np.linalg.lstsq(single, target, rcond=None)[0]
    np.testing.assert_allclose(fitted[:, 0], target - single @ weights, atol=1e-9)
    step = graph.components["expect"]
    assert step.weights == pytest.approx([weights[0] / 2, 0.0, weights[0] / 2])


def _stream(bound, rows=ROWS):
    """Score before learning; what the detector scored and what it learned."""
    seen = {"score": [], "learn": []}

    def observe(item):
        if item.node_id == "$model" and item.phase in seen:
            seen[item.phase].append(dict(item.inputs))

    graph, _ = adaptive_graph(bound, observer=observe)
    for row in rows:
        values = bound.bind(row)
        if graph.readiness.ready:
            graph.score_one(values)
        graph.learn_one(values)
    return graph, seen


def test_the_continuous_step_scores_with_the_fit_before_the_observation():
    bound = plan("adaptive_stream", LOAD)
    graph, seen = _stream(bound)
    assert bound.output_features == ["temperature", "current_residual"]
    reference = RLSRegressor(forgetting=1.0)
    before, after = [], []
    for row in ROWS:
        inputs = {"flow": row["flow"], "pressure": row["pressure"]}
        expected = reference.predict_one(inputs)
        before.append(None if expected is None else row["current"] - expected.mean[0])
        reference.learn_one(inputs, row["current"])
        expected = reference.predict_one(inputs)
        after.append(None if expected is None else row["current"] - expected.mean[0])
    # Two weights and a constant, and one more observation to measure an error.
    assert after[:3] == [None] * 3 and after[3] is not None
    learned = [item["current_residual"] for item in seen["learn"]]
    assert learned == after[3:]
    # Scoring starts later, once the detector has learned enough itself.
    scored = [item["current_residual"] for item in seen["score"]]
    assert 20 < len(scored) < len(learned)
    assert scored == before[-len(scored) :]
    assert all(
        row["temperature"] == item["temperature"]
        for row, item in zip(ROWS[-len(scored) :], seen["score"], strict=True)
    )
    step = graph.nodes[0].transformer.transformer
    assert isinstance(step, OnlineExpectedValue)
    assert step.regressor.coefficients == pytest.approx(
        {"flow": 2.0, "pressure": -0.5, "intercept": 4.0}, abs=0.05
    )


def test_the_continuous_step_is_ready_once_it_can_measure_an_error():
    step = OnlineExpectedValue("current", "gap", 2, 1.0)
    states = []
    for row in ROWS[:5]:
        state = step.readiness
        states.append((state.ready, state.observed, state.required))
        step.learn_one({key: row[key] for key in ("current", "flow", "pressure")})
    assert states == [
        (False, 0, 4),
        (False, 1, 4),
        (False, 2, 4),
        (False, 3, 4),
        (True, 4, 4),
    ]
    with pytest.raises(RuntimeError, match="has not learned enough"):
        OnlineExpectedValue("current", "gap", 2, 1.0).transform_one(
            {"current": 1.0, "flow": 1.0, "pressure": 1.0}
        )


@pytest.mark.parametrize(("forgetting", "weight"), [(1.0, 2.5), (0.9, 3.0)])
def test_forgetting_lets_the_fit_follow_a_relation_that_changes(forgetting, weight):
    step = OnlineExpectedValue("current", "gap", 1, forgetting)
    for row in [*_rows(200, 2.0), *_rows(200, 3.0)]:
        # Without the part pressure explains, current follows flow alone.
        current = row["current"] + 0.5 * row["pressure"]
        step.learn_one({"current": current, "flow": row["flow"]})
    # Every observation alike lands between the two relations; forgetting
    # leaves the earlier one behind.
    assert step.regressor.coefficients["flow"] == pytest.approx(weight, abs=0.02)


def test_an_observation_a_later_step_rejects_leaves_the_fit_as_it_was(monkeypatch):
    after = [("scale", "adaptive.standard_scaler", {"apply_to": ["current_residual"]})]
    bound = plan("adaptive_stream", {**LOAD, "result": "add"}, after)
    graph, _ = _stream(bound, ROWS[:40])
    reference, _ = _stream(bound, ROWS[:40])
    step = graph.nodes[0].transformer.transformer
    scaler = graph.nodes[1].transformer
    learn = type(scaler).learn_one
    armed = [True]

    def fragile(self, x):
        if armed[0]:
            raise ValueError("scaler broke")
        return learn(self, x)

    monkeypatch.setattr(type(scaler), "learn_one", fragile)
    weights = dict(step.regressor.coefficients)
    with pytest.raises(GraphExecutionError, match="scaler broke"):
        graph.learn_one(bound.bind(ROWS[40]))
    # The step had learned the observation before the scaler refused it.
    assert not graph.failed
    assert step.regressor.coefficients == weights
    assert step.regressor.n_samples_seen == 40
    armed[0] = False
    for row in ROWS[41:]:
        values = bound.bind(row)
        assert graph.score_one(values) == reference.score_one(values)
        graph.learn_one(values)
        reference.learn_one(values)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_expected_values_reach_real_detectors_and_resume_identically(strategy):
    config = AnomalyDetectionConfig(
        pipeline=chained_execution(strategy, steps(strategy, LOAD), SLOTS),
        checkpoint_interval=10000,
    )
    static = strategy == "static_baseline"
    constructor = (
        StaticConformalDetectionService if static else AdaptiveStreamDetectionService
    )
    service = constructor(config)
    restored = None
    # The continuous step learns for a few observations before the detector does.
    warm = 27 if static else 40
    try:
        for row in ROWS[:warm]:
            service.process_data_point(row)
        if static:
            service._training_future.result(timeout=30)
        result = service.process_data_point(ROWS[warm])
        assert result.should_persist and math.isfinite(result.anomaly_score)
        assert list(result.processed_features) == ["temperature", "current_residual"]
        assert abs(result.processed_features["current_residual"]) < 0.1
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for row in ROWS[warm + 1 : warm + 7]:
            actual = restored.process_data_point(row)
            expected = service.process_data_point(row)
            assert (
                actual.anomaly_score,
                actual.is_anomaly,
                actual.processed_features,
            ) == (
                expected.anomaly_score,
                expected.is_anomaly,
                expected.processed_features,
            )
    finally:
        if static:
            service.shutdown()
            if restored is not None:
                restored.shutdown()


def test_a_fit_counts_toward_the_known_memory():
    def known(strategy, params):
        report = estimate_resources(plan(strategy, params), 4096)
        return report.projection_state_numeric_bytes

    # A weight and a centre per feature the step uses, as doubles.
    assert known("static_baseline", {"target": "current"}) == 2 * 4 * 8
    # A covariance of the coefficients, up to eight times while an update runs.
    assert known("adaptive_stream", {"target": "current"}) == 8 * 4 * 4 * 8
    assert known("adaptive_stream", LOAD) == 8 * 3 * 3 * 8
