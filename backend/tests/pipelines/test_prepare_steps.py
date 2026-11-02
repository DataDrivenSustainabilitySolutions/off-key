"""Prepare steps: golden streams, names, ranges and the compiler's stage checks."""

import math
from array import array
from itertools import pairwise

import pytest
from off_key_core.models.pipeline_prepare import (
    PrepareFailure,
    default_suffix,
    kernel,
    stage_split,
)
from off_key_core.models.pipeline_reports import bounded_validation_report
from off_key_core.models.pipelines import compile_pipeline, validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition

DETECTORS = {
    "static_baseline": ("detector:pyod_iforest", "policy.martingale"),
    "adaptive_stream": (
        "detector:aberrant_moving_mahalanobis_distance",
        "policy.quantile",
    ),
}


def stream(component, values, **params):
    """Feed one feature's values through a step; None while it warms up."""
    step = kernel(component, params)
    state = step.initial()
    outputs = []
    for value in values:
        state, output = step.advance(state, float(value))
        outputs.append(output)
    return outputs


def failure(component, values, **params):
    with pytest.raises(PrepareFailure) as raised:
        stream(component, values, **params)
    return raised.value.reason


def test_exponential_smoothing_starts_at_the_first_value_and_waits_for_its_window():
    # alpha = 2 / (3 + 1): 1, then 1.5, then 2.25 is the first output.
    assert stream("prepare.smooth", [1, 2, 3, 4], window_size=3) == [
        None,
        None,
        2.25,
        3.125,
    ]


def test_rolling_smoothing_is_the_mean_of_the_window():
    assert stream("prepare.smooth", [1, 2, 3, 7], method="rolling", window_size=3) == [
        None,
        None,
        2.0,
        4.0,
    ]


def test_despike_replaces_a_spike_with_the_median_and_lets_a_level_shift_pass():
    values = [1, 2, 1, 2, 100, 100, 100, 100]
    assert stream("prepare.despike", values, window_size=5) == [
        None,
        None,
        None,
        None,
        2.0,  # median 2, MAD 1: 98 is far beyond 3 * 1.4826
        2.0,
        100.0,  # the third 100 is the window median
        100.0,
    ]


def test_despike_replaces_nothing_in_a_flat_window():
    # Four of five values are 5, so the MAD stays 0 and the 6 passes unchanged.
    assert stream("prepare.despike", [5, 5, 5, 5, 5, 6], window_size=5)[4:] == [
        5.0,
        6.0,
    ]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"lag": 2}, [None, None, 8.0, 12.0]),
        ({"mode": "percent"}, [None, 300.0, 125.0, 77.77777777777777]),
        ({"mode": "lag", "lag": 1}, [None, 1.0, 4.0, 9.0]),
    ],
)
def test_change_compares_with_the_value_lag_observations_back(params, expected):
    assert stream("prepare.change", [1, 4, 9, 16], **params) == expected


def test_percent_change_from_zero_skips_the_observation():
    assert failure("prepare.change", [0, 1], mode="percent") == "out_of_domain"


@pytest.mark.parametrize(
    ("statistic", "window", "expected"),
    [
        ("mean", 4, 2.5),
        ("median", 4, 2.5),
        ("median", 3, 2.0),
        ("min", 4, 1.0),
        ("max", 4, 4.0),
        ("range", 4, 3.0),
        ("std", 4, math.sqrt(5 / 3)),
    ],
)
def test_rolling_statistics_cover_the_last_values(statistic, window, expected):
    outputs = stream(
        "prepare.rolling", [4, 1, 3, 2], statistic=statistic, window_size=window
    )
    assert outputs[: window - 1] == [None] * (window - 1)
    assert outputs[-1] == pytest.approx(expected)


def test_rolling_windows_forget_the_oldest_value():
    values = [100, 1, 2, 3]
    assert stream("prepare.rolling", values, statistic="max", window_size=3) == [
        None,
        None,
        100.0,
        3.0,
    ]
    assert stream("prepare.rolling", values, statistic="median", window_size=3)[
        -1
    ] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("params", "value", "expected"),
    [
        ({"function": "log"}, math.e, 1.0),
        ({"function": "log1p"}, 0.0, 0.0),
        ({"function": "sqrt"}, 9.0, 3.0),
        ({"function": "abs"}, -2.5, 2.5),
        ({"function": "square"}, -3.0, 9.0),
        ({"function": "linear", "scale": 2.0, "offset": 1.0}, 3.0, 7.0),
    ],
)
def test_math_functions(params, value, expected):
    assert stream("prepare.math", [value], **params) == [pytest.approx(expected)]


@pytest.mark.parametrize(
    ("params", "value", "reason"),
    [
        ({"function": "log"}, 0.0, "out_of_domain"),
        ({"function": "log1p"}, -1.0, "out_of_domain"),
        ({"function": "sqrt"}, -1e-9, "out_of_domain"),
        ({"function": "square"}, 1e200, "non_finite"),
        ({"function": "linear", "scale": 1e300}, 1e300, "non_finite"),
    ],
)
def test_math_outside_its_domain_skips_the_observation(params, value, reason):
    assert failure("prepare.math", [value], **params) == reason


def test_range_check_clips_or_skips():
    assert stream("prepare.range", [-1, 0.5, 2]) == [0.0, 0.5, 1.0]
    assert stream("prepare.range", [-1, 2], low=0.0, high=None) == [0.0, 2.0]
    assert stream("prepare.range", [0.5], action="skip") == [0.5]
    assert failure("prepare.range", [2], action="skip") == "out_of_range"


def test_overflowing_window_statistics_skip_the_observation():
    assert (
        failure("prepare.rolling", [1e308, 1e308], window_size=2, statistic="mean")
        == "non_finite"
    )
    assert failure("prepare.smooth", [-1e308, 1e308], window_size=2) == "non_finite"


def test_advancing_never_changes_the_previous_state():
    step = kernel("prepare.rolling", {"statistic": "median", "window_size": 3})
    state = step.initial()
    for value in (3.0, 1.0, 2.0):
        state, _ = step.advance(state, value)
    before = [array("d", item) for item in state]
    advanced, output = step.advance(state, 10.0)
    assert [list(item) for item in state] == [list(item) for item in before]
    assert list(advanced[0]) == [1.0, 2.0, 10.0]
    assert list(advanced[1]) == [1.0, 2.0, 10.0]
    assert output == 2.0
    assert step.accepts(advanced) and not step.accepts((array("d", [2.0, 1.0]),) * 2)


@pytest.mark.parametrize(
    ("component", "params", "suffix"),
    [
        ("prepare.smooth", {}, "smooth10"),
        ("prepare.smooth", {"window_size": 30}, "smooth30"),
        ("prepare.despike", {}, "despiked"),
        ("prepare.change", {}, "diff1"),
        ("prepare.change", {"mode": "percent", "lag": 12}, "pct12"),
        ("prepare.change", {"mode": "lag", "lag": 3}, "lag3"),
        ("prepare.rolling", {}, "mean60"),
        ("prepare.rolling", {"statistic": "std", "window_size": 5}, "std5"),
        ("prepare.math", {}, "log"),
        ("prepare.math", {"function": "linear"}, "scaled"),
        ("prepare.range", {}, "clipped"),
    ],
)
def test_added_features_are_named_after_the_settings(component, params, suffix):
    assert default_suffix(component, params) == suffix


def design(strategy, steps, edges, *, last, slots=("a", "b")):
    detector, policy = DETECTORS[strategy]
    return PipelineDefinition.model_validate(
        {
            "strategy": strategy,
            "input_slots": [{"id": slot, "label": slot.title()} for slot in slots],
            "nodes": [
                {"id": "input", "kind": "source", "component": "source.aligned"},
                *steps,
                {"id": "model", "kind": "detector", "component": detector},
                {"id": "policy", "kind": "policy", "component": policy},
                {"id": "output", "kind": "output", "component": "output.evidence"},
            ],
            "edges": [
                *edges,
                {"source": last, "target": "model"},
                {"source": "model", "target": "policy"},
                {"source": "policy", "target": "output"},
            ],
            "settings": {"training_window_size": 20, "calibration_window_size": 5},
        }
    )


def chain(strategy, *steps, slots=("a", "b")):
    """input, then each (id, component, params) step in order, then the detector."""
    nodes = [
        {"id": identifier, "kind": "transform", "component": component, "params": p}
        for identifier, component, p in steps
    ]
    ids = ["input", *(identifier for identifier, _, _ in steps)]
    edges = [{"source": source, "target": target} for source, target in pairwise(ids)]
    return design(strategy, nodes, edges, last=ids[-1], slots=slots)


@pytest.mark.parametrize("strategy", sorted(DETECTORS))
def test_change_adds_features_by_default_and_both_strategies_compile_it(strategy):
    result = compile_pipeline(
        chain(
            strategy,
            ("smooth", "prepare.smooth", {"apply_to": ["a"]}),
            ("change", "prepare.change", {"result": "add"}),
        )
    )
    columns = result.features["change"]
    assert [(item.name, item.raw) for item in columns] == [
        ("a", False),
        ("b", True),
        ("a_diff1", False),
        ("b_diff1", False),
    ]
    change = next(node for node in result.definition.nodes if node.id == "change")
    # The default result is left out, so spelling it keeps the fingerprint.
    assert change.params == {"mode": "difference", "lag": 1}


def test_a_result_that_differs_from_the_default_is_kept():
    result = compile_pipeline(
        chain("adaptive_stream", ("change", "prepare.change", {"result": "replace"}))
    )
    change = next(node for node in result.definition.nodes if node.id == "change")
    assert change.params == {"result": "replace", "mode": "difference", "lag": 1}
    assert [item.name for item in result.features["change"]] == ["a", "b"]


def test_a_prepare_step_after_a_learned_step_is_an_error():
    result = validate_pipeline(
        chain(
            "adaptive_stream",
            ("scale", "adaptive.standard_scaler", {}),
            ("smooth", "prepare.smooth", {}),
        )
    )
    assert not result.valid
    assert [(item.code, item.node_id, item.message) for item in result.issues] == [
        (
            "stage",
            "smooth",
            "Smooth must come before Online standard scaling: prepare steps run "
            "before anything learns.",
        )
    ]


def test_windows_share_one_budget():
    steps = [
        (
            f"median{index}",
            "prepare.rolling",
            {"statistic": "median", "result": "replace", "window_size": 3600},
        )
        for index in range(7)
    ]
    result = validate_pipeline(chain("static_baseline", *steps))
    assert [(item.code, item.message) for item in result.issues] == [
        ("prepare_budget", "Windows hold 50,400 values; the limit is 50,000.")
    ]
    assert validate_pipeline(chain("static_baseline", *steps[:6])).valid


@pytest.mark.parametrize(
    ("params", "path", "message"),
    [
        (
            {"window_size": 10},
            ["window_size"],
            "Choose an odd number, so the window has a middle value",
        ),
        (
            {"window_size": 303},
            ["window_size"],
            "Input should be less than or equal to 301",
        ),
    ],
)
def test_despike_windows_are_odd_and_bounded(params, path, message):
    result = validate_pipeline(
        chain("adaptive_stream", ("spike", "prepare.despike", params))
    )
    issue = next(item for item in result.issues if item.node_id == "spike")
    assert (issue.parameter_path, issue.message) == (path, message)


def test_skipping_cannot_add_features():
    result = validate_pipeline(
        chain(
            "adaptive_stream",
            ("range", "prepare.range", {"action": "skip", "result": "add"}),
        )
    )
    assert [item.message for item in result.issues] == [
        "Skipping leaves values unchanged, so there is nothing to add. "
        "Choose Replace values."
    ]


def test_ranges_follow_the_steps():
    result = compile_pipeline(
        chain(
            "static_baseline",
            ("clip", "prepare.range", {"low": -1.0, "high": 3.0}),
            ("square", "prepare.math", {"function": "square", "result": "add"}),
            ("change", "prepare.change", {"apply_to": ["a"]}),
            (
                "spread",
                "prepare.rolling",
                {"apply_to": ["a"], "statistic": "range", "window_size": 5},
            ),
        )
    )
    bounds = {
        item.name: (item.minimum, item.maximum) for item in result.features["spread"]
    }
    assert bounds == {
        "a": (-1.0, 3.0),
        "b": (-1.0, 3.0),
        "a_square": (0.0, 9.0),
        "b_square": (0.0, 9.0),
        "a_diff1": (-4.0, 4.0),
        "a_range5": (0.0, 4.0),
    }


def test_a_range_check_satisfies_a_detector_that_needs_values_in_the_unit_interval():
    smoothed = (
        "smooth",
        "prepare.smooth",
        {"apply_to": ["a"]},
    )

    def needs_unit_interval(*steps):
        definition = chain("adaptive_stream", *steps)
        model = next(node for node in definition.nodes if node.id == "model")
        model.component = "detector:aberrant_half_space_trees"
        model.params = {"n_trees": 1, "height": 2, "window_size": 2, "seed": 1}
        return validate_pipeline(definition)

    assert [item.code for item in needs_unit_interval(smoothed).issues] == [
        "model_domain"
    ]
    assert needs_unit_interval(
        smoothed, ("clip", "prepare.range", {"apply_to": ["a"]})
    ).valid


def test_the_stage_ends_where_the_learned_steps_begin():
    definition = design(
        "adaptive_stream",
        [
            {
                "id": "picked",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["a"]},
            },
            {"id": "smooth", "kind": "transform", "component": "prepare.smooth"},
            {
                "id": "change",
                "kind": "transform",
                "component": "prepare.change",
                "params": {"lag": 3},
            },
            {
                "id": "raw",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["b"]},
            },
            {"id": "joined", "kind": "merge", "component": "features.merge"},
            {
                "id": "scale",
                "kind": "transform",
                "component": "adaptive.standard_scaler",
            },
        ],
        [
            {"source": "input", "target": "picked"},
            {"source": "picked", "target": "smooth"},
            {"source": "smooth", "target": "change"},
            {"source": "input", "target": "raw"},
            {"source": "change", "target": "joined", "order": 0},
            {"source": "raw", "target": "joined", "order": 1},
            {"source": "joined", "target": "scale"},
        ],
        last="scale",
    )
    compiled = compile_pipeline(definition)
    split = stage_split(compiled)
    assert split is not None
    assert split.steps == ("picked", "smooth", "change")
    # The input also feeds a learned-stage route, so it crosses the cut too.
    assert split.frontier == ("input", "change")
    assert split.columns(compiled.feature_names) == [
        "input.a",
        "input.b",
        "change.a",
        "change.a_diff3",
    ]
    # Smooth outputs from observation 10, Change three observations later.
    assert split.first_output == {"input": 1, "picked": 1, "smooth": 10, "change": 13}
    assert split.required == 13
    assert stage_split(compile_pipeline(chain("adaptive_stream"))) is None


def test_the_check_counts_the_observations_prepare_steps_take_first():
    def preparation(definition):
        return bounded_validation_report(
            validate_pipeline(definition)
        ).preparation_observations

    despiked = chain(
        "adaptive_stream",
        ("despike", "prepare.despike", {}),
        ("change", "prepare.change", {}),
    )
    # Despike has its first value at observation 11, Change one later: the
    # learned steps see the 12th observation first.
    assert preparation(despiked) == 11
    assert preparation(chain("adaptive_stream")) == 0
    broken = chain("adaptive_stream", ("change", "prepare.change", {"lag": 0}))
    assert preparation(broken) == 0
