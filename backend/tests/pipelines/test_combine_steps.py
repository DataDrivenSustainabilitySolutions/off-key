"""Aggregate, Formula and Gate in the compiler: features, names and warnings."""

from itertools import pairwise

import pytest
from aberration_core.models.pipeline_catalog import pipeline_components
from aberration_core.models.pipeline_combine import Aggregate, Formula, Gate, row_step
from aberration_core.models.pipeline_prepare import PrepareFailure, stage_split
from aberration_core.models.pipelines import compile_pipeline, validate_pipeline
from aberration_core.schemas.pipelines import PipelineDefinition

DETECTORS = {
    "static_baseline": ("detector:pyod_iforest", "policy.martingale"),
    "adaptive_stream": (
        "detector:aberrant_moving_mahalanobis_distance",
        "policy.quantile",
    ),
}
CLIP = ("clip", "prepare.range", {"low": 0.0, "high": 10.0})


def chain(*steps, strategy="adaptive_stream", slots=("a", "b", "c")):
    """input, then each (id, component, params) step in order, then the detector."""
    detector, policy = DETECTORS[strategy]
    ids = ["input", *(identifier for identifier, _, _ in steps)]
    return PipelineDefinition.model_validate(
        {
            "strategy": strategy,
            "input_slots": [{"id": slot, "label": slot.upper()} for slot in slots],
            "nodes": [
                {"id": "input", "kind": "source", "component": "source.aligned"},
                *(
                    {
                        "id": identifier,
                        "kind": "transform",
                        "component": component,
                        "params": params,
                    }
                    for identifier, component, params in steps
                ),
                {"id": "model", "kind": "detector", "component": detector},
                {"id": "policy", "kind": "policy", "component": policy},
                {"id": "output", "kind": "output", "component": "output.evidence"},
            ],
            "edges": [
                *({"source": s, "target": t} for s, t in pairwise(ids)),
                {"source": ids[-1], "target": "model"},
                {"source": "model", "target": "policy"},
                {"source": "policy", "target": "output"},
            ],
            "settings": {"training_window_size": 20, "calibration_window_size": 5},
        }
    )


def features(*steps, node=None):
    result = compile_pipeline(chain(*steps))
    return result.features[node or steps[-1][0]]


def issues(*steps):
    result = validate_pipeline(chain(*steps))
    return [
        (item.severity, item.code, item.node_id, item.parameter_path, item.message)
        for item in result.issues
    ]


def test_the_catalog_offers_the_steps_to_both_strategies():
    offered = {item.id: item for item in pipeline_components()}
    fields = {
        "prepare.aggregate": ["apply_to", "result", "function", "name"],
        "prepare.formula": ["expression", "name", "result", "apply_to", "suffix"],
        "prepare.gate": ["condition"],
    }
    for component, names in fields.items():
        item = offered[component]
        assert item.kind == "transform"
        assert set(item.strategies) == {"static_baseline", "adaptive_stream"}
        assert [field.name for field in item.fields] == names
    assert offered["prepare.formula"].fields[0].label == "Formula"


@pytest.mark.parametrize("strategy", sorted(DETECTORS))
def test_a_formula_adds_one_feature_after_the_ones_it_keeps(strategy):
    step = ("power", "prepare.formula", {"expression": "a * b", "name": "power"})
    result = compile_pipeline(chain(step, strategy=strategy))
    columns = result.features["power"]
    assert [(item.name, item.slots, item.raw) for item in columns] == [
        ("a", ["a"], True),
        ("b", ["b"], True),
        ("c", ["c"], True),
        ("power", ["a", "b"], False),
    ]
    node = next(item for item in result.definition.nodes if item.id == "power")
    # The default result is left out of the normalized settings.
    assert node.params == {"expression": "a * b", "name": "power"}


def test_a_formula_without_a_name_is_called_formula_and_can_replace_its_inputs():
    assert [
        item.name
        for item in features(("f", "prepare.formula", {"expression": "a + 1"}))
    ] == [
        "a",
        "b",
        "c",
        "formula",
    ]
    replaced = features(
        (
            "f",
            "prepare.formula",
            {"expression": "a - b", "result": "replace", "name": "a"},
        )
    )
    # Replacing frees the names it reads, so the result may take one of them.
    assert [item.name for item in replaced] == ["c", "a"]


def test_an_aggregate_combines_the_features_it_uses():
    assert [item.name for item in features(("mean", "prepare.aggregate", {}))] == [
        "a",
        "b",
        "c",
        "mean",
    ]
    peak = features(
        (
            "peak",
            "prepare.aggregate",
            {
                "apply_to": ["c", "a"],
                "function": "max",
                "name": "peak",
                "result": "replace",
            },
        )
    )
    assert [(item.name, item.slots) for item in peak] == [
        ("b", ["b"]),
        ("peak", ["a", "c"]),
    ]


@pytest.mark.parametrize(
    ("function", "bounds"),
    [
        ("mean", (-1.0, 10.0)),
        ("sum", (-1.0, 14.0)),
        ("min", (-1.0, 4.0)),
        ("max", (0.0, 10.0)),
        ("std", (0.0, 11.0)),
        ("range", (0.0, 11.0)),
    ],
)
def test_an_aggregate_knows_the_range_of_its_result(function, bounds):
    columns = features(
        ("clip_a", "prepare.range", {"apply_to": ["a"], "low": 0.0, "high": 10.0}),
        ("clip_b", "prepare.range", {"apply_to": ["b"], "low": -1.0, "high": 4.0}),
        ("agg", "prepare.aggregate", {"apply_to": ["a", "b"], "function": function}),
    )
    assert (columns[-1].minimum, columns[-1].maximum) == bounds


def test_a_formula_knows_the_range_of_its_result():
    columns = features(CLIP, ("f", "prepare.formula", {"expression": "a * b - c"}))
    assert (columns[-1].minimum, columns[-1].maximum) == (-10.0, 100.0)


def test_a_gate_passes_its_features_on_unchanged():
    gate = ("gate", "prepare.gate", {"condition": "a > 1"})
    passed = features(CLIP, gate)
    # Each continues the feature before the Gate, and nothing else changes.
    assert [item.previous for item in passed] == [
        f"clip.{item.name}" for item in passed
    ]
    assert [item.model_dump(exclude={"previous"}) for item in passed] == [
        item.model_dump(exclude={"previous"}) for item in features(CLIP, node="clip")
    ]


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        (
            [("f", "prepare.formula", {})],
            [
                (
                    "error",
                    "parameters",
                    "f",
                    ["expression"],
                    "Write a formula, such as dc_voltage * dc_current.",
                )
            ],
        ),
        (
            [("g", "prepare.gate", {"condition": ""})],
            [
                (
                    "error",
                    "parameters",
                    "g",
                    ["condition"],
                    "Write a condition, such as dc_current > 1.",
                )
            ],
        ),
        (
            [("f", "prepare.formula", {"expression": "a * bb"})],
            [
                (
                    "error",
                    "formula",
                    "f",
                    ["expression"],
                    "Unknown feature bb at character 5. Did you mean b?",
                )
            ],
        ),
        (
            [("f", "prepare.formula", {"expression": "a *"})],
            [
                (
                    "error",
                    "formula",
                    "f",
                    ["expression"],
                    "The expression ends too early at character 4.",
                )
            ],
        ),
        (
            [("g", "prepare.gate", {"condition": "a"})],
            [
                (
                    "error",
                    "formula",
                    "g",
                    ["condition"],
                    "Write a condition, such as dc_current > 1.",
                )
            ],
        ),
        (
            [("f", "prepare.formula", {"expression": "a", "name": "b"})],
            [
                (
                    "error",
                    "scope",
                    "f",
                    ["name"],
                    "b already exists. Choose another name.",
                )
            ],
        ),
        (
            [("f", "prepare.formula", {"expression": "a", "name": "2x"})],
            [
                (
                    "error",
                    "parameters",
                    "f",
                    ["name"],
                    "Use letters, digits and underscores, and start with a letter or "
                    "an underscore.",
                )
            ],
        ),
        (
            [("m", "prepare.aggregate", {"apply_to": ["a"]})],
            [
                (
                    "error",
                    "scope",
                    "m",
                    ["apply_to"],
                    "Aggregate needs at least 2 features.",
                )
            ],
        ),
    ],
)
def test_problems_point_at_their_setting(steps, expected):
    assert issues(*steps) == expected


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            ("f", "prepare.formula", {"expression": "b / a"}),
            [
                (
                    "warning",
                    "values",
                    "f",
                    ["expression"],
                    "Division by a: observations where it is 0 are skipped.",
                )
            ],
        ),
        (
            ("f", "prepare.formula", {"expression": "log(a - 20)"}),
            [
                (
                    "error",
                    "values",
                    "f",
                    ["expression"],
                    "log of a - 20: every value is at or below 0, so every "
                    "observation would be skipped.",
                )
            ],
        ),
        (
            ("f", "prepare.formula", {"expression": "2 * 3"}),
            [
                (
                    "warning",
                    "values",
                    "f",
                    ["expression"],
                    "The formula reads no feature, so its value never changes.",
                )
            ],
        ),
        (
            ("g", "prepare.gate", {"condition": "a > 20"}),
            [
                (
                    "error",
                    "values",
                    "g",
                    ["condition"],
                    "The condition is never true, so no observation would reach "
                    "the detector.",
                )
            ],
        ),
        (
            ("g", "prepare.gate", {"condition": "a >= 0 or b > 5"}),
            [
                (
                    "warning",
                    "values",
                    "g",
                    ["condition"],
                    "The condition is always true, so the gate holds nothing back.",
                )
            ],
        ),
        (("g", "prepare.gate", {"condition": "a > 5"}), []),
        (
            ("log", "prepare.math", {"function": "log"}),
            [
                (
                    "warning",
                    "values",
                    "log",
                    ["function"],
                    f"log of {name}: values at or below 0 are skipped.",
                )
                for name in "abc"
            ],
        ),
        (
            ("pct", "prepare.change", {"mode": "percent", "apply_to": ["b"]}),
            [
                (
                    "warning",
                    "values",
                    "pct",
                    ["mode"],
                    "Percent change of b: observations compared with a 0 are skipped.",
                )
            ],
        ),
    ],
)
def test_values_a_step_will_skip_are_known_before_it_runs(step, expected):
    assert issues(CLIP, step) == expected


def test_readings_are_named_by_their_label_in_warnings():
    assert issues(("f", "prepare.formula", {"expression": "sqrt(a)"})) == [
        (
            "warning",
            "values",
            "f",
            ["expression"],
            "sqrt of A: values below 0 are skipped.",
        )
    ]


def test_the_steps_belong_to_the_prepare_stage():
    split = stage_split(
        compile_pipeline(
            chain(
                ("gate", "prepare.gate", {"condition": "a > 0"}),
                ("power", "prepare.formula", {"expression": "a * b", "name": "power"}),
                ("mean", "prepare.aggregate", {"apply_to": ["a", "c"]}),
                ("scale", "adaptive.standard_scaler", {}),
            )
        )
    )
    assert split is not None
    assert split.steps == ("gate", "power", "mean")
    assert split.frontier == ("mean",)
    # The steps keep no window, so the first observation is prepared at once.
    assert split.required == 1
    assert issues(
        ("scale", "adaptive.standard_scaler", {}),
        ("gate", "prepare.gate", {"condition": "a > 0"}),
    ) == [
        (
            "error",
            "stage",
            "gate",
            None,
            "Gate must come before Online standard scaling: prepare steps run "
            "before anything learns.",
        )
    ]


def test_row_steps_compute_on_one_observation():
    row = {"a": 2.0, "b": 3.0, "c": -1.0}
    aggregate = row_step("prepare.aggregate", {"function": "std"}, list(row))
    assert isinstance(aggregate, Aggregate)
    assert aggregate.apply(row)["std"] == pytest.approx(2.081665999)
    formula = row_step(
        "prepare.formula",
        {"expression": "a ^ 2 + b", "result": "replace", "name": "y"},
        list(row),
    )
    assert isinstance(formula, Formula)
    assert formula.apply(row) == {"c": -1.0, "y": 7.0}
    gate = row_step("prepare.gate", {"condition": "c < 0 and a > 1"}, list(row))
    assert isinstance(gate, Gate)
    assert gate.opens(row) and not gate.opens({**row, "a": 0.0})
    with pytest.raises(PrepareFailure) as raised:
        row_step("prepare.formula", {"expression": "a / (b - 3)"}, list(row)).apply(row)
    assert raised.value.reason == "out_of_domain"
    huge = {"a": 1e308, "b": 1e308, "c": 1e308}
    with pytest.raises(PrepareFailure) as raised:
        row_step("prepare.aggregate", {"function": "sum"}, list(huge)).apply(huge)
    assert raised.value.reason == "non_finite"


MEAN = ("mean", "prepare.aggregate", {"function": "mean", "name": "m"})


def test_a_formula_for_each_feature_adds_one_feature_per_feature():
    each = (
        "dev",
        "prepare.formula",
        {"expression": "x / m - 1", "apply_to": ["a", "b"], "suffix": "dev"},
    )
    result = compile_pipeline(chain(MEAN, each))
    added = {item.name: item for item in result.features["dev"]}
    assert list(added) == ["a", "b", "c", "m", "a_dev", "b_dev"]
    assert added["a_dev"].steps == ["dev"]
    assert added["a_dev"].slots == ["a", "b", "c"]
    plain = ("dev", "prepare.formula", {"expression": "x / m - 1", "apply_to": ["a"]})
    assert [item.name for item in features(MEAN, plain)][-1] == "a_formula"


def test_a_formula_for_each_feature_can_replace_the_features():
    each = (
        "dev",
        "prepare.formula",
        {"expression": "x / m - 1", "apply_to": ["a", "b"], "result": "replace"},
    )
    assert [item.name for item in features(MEAN, each)] == ["a", "b", "c", "m"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        (
            {"expression": "x + 1"},
            ("error", "formula", ["expression"], "x stands for each feature only"),
        ),
        (
            {"expression": "x", "apply_to": ["z"]},
            ("error", "scope", ["apply_to"], "z is not available at this step."),
        ),
        (
            {"expression": "x", "apply_to": ["a"], "name": "y"},
            ("error", "parameters", [], "A formula for each feature names"),
        ),
        (
            {"expression": "m * 2", "apply_to": ["a"]},
            ("warning", "values", ["expression"], "The formula never reads x"),
        ),
        (
            {"expression": "x", "apply_to": ["a"], "suffix": "dev"},
            ("error", "scope", ["suffix"], "a_dev"),
        ),
    ],
)
def test_a_formula_for_each_feature_reports_its_problems(params, expected):
    taken = ("taken", "prepare.formula", {"expression": "a", "name": "a_dev"})
    found = issues(MEAN, taken, ("each", "prepare.formula", params))
    severity, code, path, text = expected
    assert any(
        item[0] == severity and item[1] == code and item[3] == path and text in item[4]
        for item in found
    ), found


def test_a_formula_for_each_feature_computes_on_one_observation():
    row = {"a": 16.8, "b": 15.2, "m": 16.0}
    added = row_step(
        "prepare.formula",
        {"expression": "x / m - 1", "apply_to": ["a", "b"], "suffix": "dev"},
        list(row),
    ).apply(row)
    assert added["a_dev"] == pytest.approx(0.05) and added["b_dev"] == pytest.approx(
        -0.05
    )
    assert added["a"] == 16.8
    replaced = row_step(
        "prepare.formula",
        {"expression": "x / m - 1", "apply_to": ["a", "b"], "result": "replace"},
        list(row),
    ).apply(row)
    assert replaced == pytest.approx({"a": 0.05, "b": -0.05, "m": 16.0})
