"""Steps that read the row: starting over, holding, relations and Calculate."""

import math
import pickle
import random
import sys
from array import array
from itertools import pairwise

import numpy as np
import pytest
from off_key_core.models.pipeline_combine import row_step
from off_key_core.models.pipeline_prepare import (
    PrepareFailure,
    default_suffix,
    kernel,
    prepared_bounds,
)
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineExecutionConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import PrepareRejected, PrepareStage
from off_key_mqtt_radar.pipelines.resources import estimate_resources

from tests.support.pipelines import template

pytestmark = pytest.mark.radar_integration

# Power per observation, the energy and the observations of each session, the
# level a session started at, and how power moves with b.
STEPS = [
    (
        "calc",
        "prepare.calculate",
        {"formulas": "power = a * b\nstart = if(b > 2, 1, 0)"},
    ),
    (
        "energy",
        "prepare.accumulate",
        {"apply_to": ["power"], "reset_when": "start == 1"},
    ),
    (
        "seen",
        "prepare.accumulate",
        {"apply_to": ["a"], "function": "count", "reset_when": "start == 1"},
    ),
    ("level", "prepare.hold", {"apply_to": ["a"], "update_when": "start == 1"}),
    (
        "moves",
        "prepare.relation",
        {"against": "b", "apply_to": ["power"], "statistic": "slope", "window_size": 3},
    ),
]


def design(strategy="adaptive_stream", steps=STEPS, slots=("a", "b")):
    data = template(strategy).model_dump(mode="json")
    data["input_slots"] = [{"id": key, "label": key.upper()} for key in slots]
    data["settings"].update(training_window_size=20, calibration_window_size=5)
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    if strategy == "adaptive_stream":
        detector.update(
            component="detector:aberrant_moving_mahalanobis_distance",
            params={"window_size": 5},
        )
    else:
        detector["params"] = {"n_estimators": 10}
    data["nodes"].extend(
        {"id": key, "kind": "transform", "component": component, "params": params}
        for key, component, params in steps
    )
    data["edges"] = [edge for edge in data["edges"] if edge["source"] != "input"] + [
        {"source": source, "target": target}
        for source, target in pairwise(
            ["input", *(key for key, _, _ in steps), "detector"]
        )
    ]
    return PipelineDefinition.model_validate(data)


def checked(*steps, slots=("a", "b")):
    """What the compiler says about a chain of steps, valid or not."""
    return validate_pipeline(design(steps=list(steps), slots=slots))


def issues(result, severity="error"):
    return [
        (item.code, item.parameter_path, item.message)
        for item in result.issues
        if item.severity == severity
    ]


def features(result, node):
    return {item.name: item for item in result.features[node]}


def execution(strategy="adaptive_stream", steps=STEPS):
    definition = compile_pipeline(design(strategy, steps)).definition
    bindings = [
        dict(
            slot_id=key,
            reading_id=key,
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{key}",
            input_key=key,
        )
        for key in ("a", "b")
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )


def reading(index):
    return {"a": float(index % 7 - 3), "b": 1.0 + (index % 5) / 2}


@pytest.mark.parametrize(
    "function,expected",
    [
        ("sum", [2.0, 7.0, 4.0, 5.0, 3.0]),
        ("min", [2.0, 2.0, 4.0, 1.0, -2.0]),
        ("max", [2.0, 5.0, 4.0, 4.0, 4.0]),
        ("count", [1.0, 2.0, 1.0, 2.0, 3.0]),
    ],
)
def test_an_accumulation_starts_over_with_the_observation_that_resets(
    function, expected
):
    step = kernel("prepare.accumulate", {"function": function})
    state = step.initial()
    values = [2.0, 5.0, 4.0, 1.0, -2.0]
    resets = [False, False, True, False, False]
    for value, reset, result in zip(values, resets, expected, strict=True):
        before = pickle.dumps(state)
        state, actual = step.advance(state, value, reset)
        assert actual == result and step.accepts(state)
        # The earlier state is left as it was, so a rejection can keep it.
        assert pickle.dumps(pickle.loads(before)) == before
    # A reset on the first observation changes nothing.
    assert step.advance(step.initial(), 3.0, True) == step.advance(step.initial(), 3.0)
    assert default_suffix("prepare.accumulate", {"function": "count"}) == "count"
    counted = prepared_bounds("prepare.accumulate", {"function": "count"}, (-5.0, 5.0))
    assert counted == (1.0, None)


def test_a_hold_keeps_the_value_from_the_last_observation_its_condition_held():
    step = kernel("prepare.hold", {"update_when": "a > 0"})
    state = step.initial()
    outputs = []
    for value, update in [(3.0, False), (4.0, False), (5.0, True), (6.0, False)]:
        state, actual = step.advance(state, value, update)
        assert step.accepts(state)
        outputs.append(actual)
    # The first observation is taken although the condition does not hold.
    assert outputs == [3.0, 3.0, 5.0, 5.0]
    assert step.lead == 0 and step.window == 0
    assert not step.accepts((False, 1.0)) and not step.accepts((True, math.inf))
    assert not step.accepts((True, 1.0, 0.0))
    assert default_suffix("prepare.hold", {}) == "held"
    assert prepared_bounds("prepare.hold", {}, (-1.0, 4.0)) == (-1.0, 4.0)


def _relation(statistic, own, other):
    """numpy's value of a relation between two windows."""
    slope, intercept = np.polyfit(other, own, 1)
    return {
        "correlation": np.corrcoef(own, other)[0, 1],
        "covariance": np.cov(own, other, ddof=1)[0, 1],
        "slope": slope,
        "residual": own[-1] - (intercept + slope * other[-1]),
    }[statistic]


RELATIONS = ["correlation", "covariance", "slope", "residual"]


@pytest.mark.parametrize("statistic", RELATIONS)
@pytest.mark.parametrize("size", [3, 8, 40])
def test_relations_match_numpy(statistic, size):
    rng = random.Random(size)
    others = [rng.gauss(10, 3) for _ in range(150)]
    values = [2.5 * item + rng.gauss(0, 2) for item in others]
    params = {"against": "b", "statistic": statistic, "window_size": size}
    step = kernel("prepare.relation", params)
    low, high = prepared_bounds("prepare.relation", params, (None, None))
    assert (low, high) == ((-1.0, 1.0) if statistic == "correlation" else (None, None))
    state = step.initial()
    for index, (value, other) in enumerate(zip(values, others, strict=True)):
        state, actual = step.advance(pickle.loads(pickle.dumps(state)), value, other)
        assert step.accepts(state)
        if index + 1 < size:
            assert actual is None
            continue
        own = np.array(values[index + 1 - size : index + 1])
        against = np.array(others[index + 1 - size : index + 1])
        assert actual == pytest.approx(
            _relation(statistic, own, against), rel=1e-7, abs=1e-7
        )
    assert step.lead == size - 1 and step.window == size
    suffix = {"correlation": "corr", "covariance": "cov", "slope": "beta"}.get(
        statistic, "resid"
    )
    assert default_suffix("prepare.relation", params) == f"{suffix}{size}"


@pytest.mark.parametrize("statistic", RELATIONS)
def test_a_flat_window_has_no_direction(statistic):
    step = kernel(
        "prepare.relation", {"against": "b", "statistic": statistic, "window_size": 3}
    )

    def last(pairs):
        state = step.initial()
        for value, other in pairs:
            state, actual = step.advance(state, value, other)
        return actual

    # The other feature stays at 2: the fit is the mean, 3, and the latest
    # value lies 2 above it.
    flat_other = last([(1.0, 2.0), (3.0, 2.0), (5.0, 2.0)])
    assert flat_other == (2.0 if statistic == "residual" else 0.0)
    assert last([(4.0, 1.0), (4.0, 2.0), (4.0, 7.0)]) == 0.0
    assert last([(4.0, 2.0), (4.0, 2.0), (4.0, 2.0)]) == 0.0
    # The mean of three 0.1 rounds to another number; the window is flat still.
    assert math.fsum([0.1] * 3) / 3 != 0.1
    assert last([(0.1, 1.0), (0.1, 2.0), (0.1, 3.0)]) == 0.0
    assert last([(1.0, 0.1), (2.0, 0.1), (4.0, 0.1)]) == (
        pytest.approx(5 / 3) if statistic == "residual" else 0.0
    )


@pytest.mark.parametrize("scale", [1e150, 1e-150])
def test_relations_of_very_large_and_very_small_values_stay_exact(scale):
    pairs = [(1.0, 1.0), (2.0, 3.0), (4.0, 2.0), (3.0, 5.0)]
    expected = {}
    for statistic in RELATIONS:
        for factor in (1.0, scale):
            step = kernel(
                "prepare.relation",
                {"against": "b", "statistic": statistic, "window_size": 4},
            )
            state = step.initial()
            for value, other in pairs:
                state, actual = step.advance(state, value * factor, other * factor)
            expected.setdefault(statistic, actual)
            # Scaling both features leaves correlation and slope as they are
            # and scales a residual; only the covariance squares the scale.
            power = {"correlation": 0, "slope": 0, "residual": 1}.get(statistic)
            if factor == 1.0 or power is None:
                continue
            assert actual == pytest.approx(expected[statistic] * factor**power)
    step = kernel("prepare.relation", {"against": "b", "statistic": "covariance"})
    state = step.initial()
    for index in range(59):
        state, _ = step.advance(state, 1e200 * index, 1e200 * index)
    with pytest.raises(PrepareFailure, match="finite"):
        step.advance(state, 1e200 * 60, 1e200 * 60)
    with pytest.raises(ValueError, match="other feature"):
        step.advance(step.initial(), 1.0)


@pytest.mark.parametrize("statistic", RELATIONS)
def test_relations_keep_small_differences_of_large_values(statistic):
    def last(pairs):
        step = kernel(
            "prepare.relation",
            {"against": "b", "statistic": statistic, "window_size": len(pairs)},
        )
        state = step.initial()
        for value, other in pairs:
            state, actual = step.advance(state, value, other)
        return actual

    # The mean of each large window is no float, so nothing may depend on it.
    small = [(0.0, 0.0), (0.0, 2.0), (2.0, 0.0), (2.0, 2.0), (2.0, 4.0)]
    large = [(1e16 + value, -1e16 + other) for value, other in small]
    assert last(large) == pytest.approx(last(small))
    assert last(small) == pytest.approx(
        _relation(statistic, *np.array(small).T), abs=1e-12
    )


def test_a_relation_refuses_states_of_another_shape():
    step = kernel("prepare.relation", {"against": "b", "window_size": 3})
    state = step.initial()
    for index in range(4):
        state, _ = step.advance(state, float(index), float(-index))
    assert step.accepts(state) and step.accepts(step.initial())
    own, other = state
    assert not step.accepts((own, other[1:]))
    assert not step.accepts((own,))
    assert not step.accepts((list(own), list(other)))
    assert not step.accepts((own + own, other + other))


def test_an_accumulation_names_checks_and_keeps_its_fingerprint():
    plain = checked(("total", "prepare.accumulate", {}))
    node = next(item for item in plain.definition.nodes if item.id == "total")
    # Left out when unused, so accumulations saved before keep their fingerprint.
    assert node.params == {"function": "sum"}
    counted = checked(
        ("total", "prepare.accumulate", {"function": "count", "reset_when": "b > 2"})
    )
    assert counted.valid and issues(counted, "warning") == []
    column = features(counted, "total")["a_count"]
    assert (column.minimum, column.maximum, column.steps) == (1.0, None, ["total"])
    for condition, message in [
        ("c > 2", "Unknown feature c at character 1."),
        ("a + 2", "Write a condition, such as dc_current > 1."),
    ]:
        result = checked(("total", "prepare.accumulate", {"reset_when": condition}))
        assert issues(result) == [("formula", ["reset_when"], message)]
    empty = checked(("total", "prepare.accumulate", {"reset_when": ""}))
    assert issues(empty) == [
        (
            "parameters",
            ["reset_when"],
            "Write a condition, or leave it empty to never start over.",
        )
    ]


@pytest.mark.parametrize(
    "component,parameter,condition,message",
    [
        (
            "prepare.accumulate",
            "reset_when",
            "1 > 2",
            "The condition is never true, so the accumulation never starts over.",
        ),
        (
            "prepare.accumulate",
            "reset_when",
            "2 > 1",
            "The condition is always true, so every observation starts over.",
        ),
        (
            "prepare.hold",
            "update_when",
            "1 > 2",
            "The condition is never true, so every feature keeps its first value.",
        ),
        (
            "prepare.hold",
            "update_when",
            "2 > 1",
            "The condition is always true, so the step holds nothing.",
        ),
        (
            "prepare.hold",
            "update_when",
            "a > 1 / b",
            "Division by B: observations where it is 0 are skipped.",
        ),
    ],
)
def test_a_condition_that_cannot_change_or_skips_values_is_reported(
    component, parameter, condition, message
):
    result = checked(("step", component, {parameter: condition}))
    assert result.valid
    assert issues(result, "warning") == [("values", [parameter], message)]


def test_a_hold_needs_a_condition_and_adds_held_features():
    missing = checked(("hold", "prepare.hold", {}))
    assert issues(missing) == [
        ("parameters", ["update_when"], "Write a condition, such as dc_current > 1.")
    ]
    result = checked(
        ("limit", "prepare.range", {"apply_to": ["a"], "low": -3, "high": 3}),
        ("hold", "prepare.hold", {"update_when": "b >= 1", "apply_to": ["a"]}),
    )
    assert result.valid
    columns = features(result, "hold")
    assert list(columns) == ["a", "b", "a_held"]
    held = columns["a_held"]
    assert (held.minimum, held.maximum, held.slots) == (-3.0, 3.0, ["a"])
    assert held.steps == ["limit", "hold"] and not held.raw


def test_a_relation_compares_the_other_features_with_one():
    result = checked(("moves", "prepare.relation", {"against": "b"}), slots="abc")
    assert result.valid
    columns = features(result, "moves")
    # Every feature but the one compared with, each with both readings behind it.
    assert list(columns) == ["a", "b", "c", "a_corr60", "c_corr60"]
    added = columns["c_corr60"]
    assert (added.minimum, added.maximum, added.slots) == (-1.0, 1.0, ["b", "c"])
    assert columns["b"].slots == ["b"] and columns["b"].raw
    replaced = checked(
        (
            "moves",
            "prepare.relation",
            {"against": "a", "statistic": "residual", "result": "replace"},
        )
    )
    column = features(replaced, "moves")["b"]
    assert (column.minimum, column.maximum, column.slots) == (None, None, ["a", "b"])
    assert column.steps == ["moves"] and features(replaced, "moves")["a"].raw


@pytest.mark.parametrize(
    "params,slots,expected",
    [
        (
            {},
            "ab",
            ("parameters", ["against"], "Choose the feature to compare with."),
        ),
        (
            {"against": "c"},
            "ab",
            ("scope", ["against"], "c is not available at this step."),
        ),
        (
            {"against": "b", "apply_to": ["a", "b"]},
            "ab",
            (
                "scope",
                ["apply_to"],
                "b is the feature the others are compared with. Leave it out of "
                "Applies to.",
            ),
        ),
        (
            {"against": "a"},
            "a",
            (
                "scope",
                ["apply_to"],
                "Only a arrives here. A Rolling relation needs another feature to "
                "compare with it.",
            ),
        ),
        (
            {"against": "b", "window_size": 2},
            "ab",
            (
                "parameters",
                ["window_size"],
                "Input should be greater than or equal to 3",
            ),
        ),
    ],
)
def test_a_relation_says_what_it_cannot_compare(params, slots, expected):
    result = checked(("moves", "prepare.relation", params), slots=slots)
    assert issues(result) == [expected]


def test_calculate_writes_features_in_order_and_each_line_reads_the_ones_above():
    text = "power = a * b\n# a note\n\n  a = a / 2\nratio = power / a\n`b` = sqrt(b)"
    step = row_step("prepare.calculate", {"formulas": text}, ["a", "b"])
    row = step.apply({"a": 4.0, "b": 9.0})
    # a keeps its place, b is replaced where it stands, new features follow.
    assert row == {"a": 2.0, "b": 3.0, "power": 36.0, "ratio": 18.0}
    assert list(row) == ["a", "b", "power", "ratio"]
    result = checked(("calc", "prepare.calculate", {"formulas": text}))
    assert result.valid
    columns = features(result, "calc")
    assert list(columns) == list(row)
    # A feature computed from itself continues its trail; the others start here.
    assert columns["a"].previous == "input.a" and columns["a"].steps == ["calc"]
    assert columns["power"].previous is None and columns["power"].slots == ["a", "b"]
    assert (columns["b"].minimum, columns["b"].maximum) == (0.0, None)
    assert issues(result, "warning") == [
        (
            "values",
            ["formulas"],
            "Line 5: Division by A: observations where it is 0 are skipped.",
        ),
        (
            "values",
            ["formulas"],
            "Line 6: sqrt of B: values below 0 are skipped.",
        ),
    ]
    with pytest.raises(PrepareFailure, match=r"^ratio: Division by 0$"):
        step.apply({"a": 0.0, "b": 9.0})


def test_calculate_ranges_follow_the_lines_above():
    result = checked(
        ("limit", "prepare.range", {"low": 0, "high": 2}),
        (
            "calc",
            "prepare.calculate",
            {"formulas": "double = 2 * a\nshare = double / (double + b + 1)"},
        ),
    )
    assert result.valid and issues(result, "warning") == []
    columns = features(result, "calc")
    assert (columns["double"].minimum, columns["double"].maximum) == (0.0, 4.0)
    assert (columns["share"].minimum, columns["share"].maximum) == (0.0, 4.0)


@pytest.mark.parametrize(
    "text,code,message,fix",
    [
        (
            None,
            "parameters",
            "Write a line such as power = dc_voltage * dc_current.",
            None,
        ),
        (
            "# only a note\n\n",
            "formula",
            "Write a line such as power = dc_voltage * dc_current.",
            None,
        ),
        (
            "power = a * b\nratio = powr / b",
            "formula",
            "Line 2: Unknown feature powr at character 9. Did you mean power?",
            (22, 26, "power"),
        ),
        (
            "power = a * b\nratio 3",
            "formula",
            "Line 2: Start with a name and =, such as power = dc_voltage * dc_current.",
            None,
        ),
        (
            "p == 3",
            "formula",
            "Line 1: Start with a name and =, such as power = dc_voltage * dc_current.",
            None,
        ),
        (
            "power = a * b\n`my ratio` = 3",
            "formula",
            "Line 2: my ratio is not a feature here. For a new feature, use "
            "letters, digits and underscores, and start with a letter or an "
            "underscore.",
            None,
        ),
        (
            "\npower = a * (b",
            "formula",
            "Line 2: Close the parenthesis opened at character 13.",
            None,
        ),
        (
            "flag = a > b",
            "formula",
            "Line 1: A formula computes a number. For 1 or 0, write "
            "if(condition, 1, 0); to hold observations back by a condition, use "
            "a Gate step.",
            None,
        ),
        ("p =", "formula", "Line 1: Write an expression.", None),
        (
            "\n".join(f"v{index} = {index}" for index in range(33)),
            "formula",
            "Keep a Calculate step to 32 formulas; add another step for more.",
            None,
        ),
    ],
)
def test_calculate_names_the_line_and_the_character_of_a_problem(
    text, code, message, fix
):
    params = {} if text is None else {"formulas": text}
    result = checked(("calc", "prepare.calculate", params))
    assert issues(result) == [(code, ["formulas"], message)]
    found = next(item.fix for item in result.issues)
    assert (found and (found.start, found.end, found.text)) == fix


def test_the_stage_reads_conditions_and_the_compared_feature_from_the_row():
    plan = ExecutionPlan(execution())
    stage = PrepareStage(plan)
    rows = [(1, 1), (2, 3), (3, 1), (4, 2), (5, 4), (6, 0)]
    outputs = [stage.run({"a": float(a), "b": float(b)}) for a, b in rows]
    assert stage.required == 3 and stage.rejected == 0
    assert outputs[2] == {
        "moves.a": 3.0,
        "moves.b": 1.0,
        "moves.power": 3.0,
        "moves.start": 0.0,
        # The second observation started over: 6 + 3, two observations in.
        "moves.power_total": 9.0,
        "moves.a_count": 2.0,
        "moves.a_held": 2.0,
        # Power 1, 6, 3 against b 1, 3, 1.
        "moves.power_beta3": pytest.approx(2.0),
    }
    assert [item["moves.power_total"] for item in outputs[3:]] == [17.0, 20.0, 20.0]
    assert [item["moves.a_count"] for item in outputs[3:]] == [3.0, 1.0, 2.0]
    assert [item["moves.a_held"] for item in outputs[3:]] == [2.0, 5.0, 5.0]


def test_a_rejected_condition_or_formula_leaves_every_state_as_it_was():
    steps = [
        *STEPS[:2],
        ("level", "prepare.hold", {"apply_to": ["a"], "update_when": "1 / a > 0"}),
        *STEPS[4:],
    ]
    plan = ExecutionPlan(execution(steps=steps))
    stage = PrepareStage(plan)
    for index in range(1, 6):
        stage.run({"a": float(index), "b": float(index % 3)})
    before = pickle.dumps(stage.export_state()["states"])
    with pytest.raises(PrepareRejected, match="Division by 0") as failure:
        stage.run({"a": 0.0, "b": 3.0})
    assert failure.value.node_id == "level"
    assert pickle.dumps(stage.export_state()["states"]) == before
    assert stage.rejected == 1
    restored = PrepareStage(plan)
    restored.load_state(pickle.loads(pickle.dumps(stage.export_state())))
    following = {"a": 7.0, "b": 2.5}
    assert restored.run(following) == stage.run(following)
    # A checkpoint whose relation windows differ in length is refused.
    broken = pickle.loads(pickle.dumps(stage.export_state()))
    own, other = broken["states"]["moves"][0]
    broken["states"]["moves"][0] = (own, other[1:])
    with pytest.raises(ValueError, match="state of moves is invalid"):
        PrepareStage(plan).load_state(broken)


def test_relation_windows_count_toward_the_known_memory():
    def known(steps):
        plan = ExecutionPlan(execution(steps=steps))
        return estimate_resources(plan, 4096).prepare_state_bytes

    relation = {"against": "b", "apply_to": ["a"], "window_size": 500}
    paired = known([("moves", "prepare.relation", relation)])
    single = known(
        [("mean", "prepare.rolling", {"apply_to": ["a"], "window_size": 500})]
    )
    # A relation keeps a second window per feature, of the feature it is
    # compared with, and each can be alive twice while an observation is staged.
    window = sys.getsizeof(array("d")) + 8 * 500
    assert paired - single == 2 * (window + sys.getsizeof((0, 0)) - sys.getsizeof((0,)))


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_row_reading_steps_reach_real_detectors_and_resume_identically(strategy):
    config = AnomalyDetectionConfig(
        pipeline=execution(strategy), checkpoint_interval=10000
    )
    constructor = (
        StaticConformalDetectionService
        if strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    service = constructor(config)
    restored = None
    try:
        for index in range(27):
            service.process_data_point(reading(index))
        if strategy == "static_baseline":
            service._training_future.result(timeout=30)
        result = service.process_data_point(reading(27))
        assert result.should_persist and math.isfinite(result.anomaly_score)
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for index in range(28, 34):
            actual = restored.process_data_point(reading(index))
            expected = service.process_data_point(reading(index))
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
        if strategy == "static_baseline":
            service.shutdown()
            if restored is not None:
                restored.shutdown()
