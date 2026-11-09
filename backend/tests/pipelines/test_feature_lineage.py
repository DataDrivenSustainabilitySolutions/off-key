"""Each feature's recipe, each Prepare step's warm-up and one-click formula fixes."""

from itertools import pairwise

import pytest
from aberration_core.models.pipeline_formula import FormulaError, parse, written
from aberration_core.models.pipeline_reports import bounded_validation_report
from aberration_core.models.pipelines import compile_pipeline, validate_pipeline
from aberration_core.schemas.pipelines import PipelineDefinition

from tests.support.pipelines import branched


def chain(*steps, slots=("a", "b", "c")):
    """input, each (id, component, params) step in order, then the detector."""
    ids = ["input", *(identifier for identifier, _, _ in steps)]
    return PipelineDefinition.model_validate(
        {
            "strategy": "adaptive_stream",
            "input_slots": [{"id": slot, "label": slot.upper()} for slot in slots],
            "nodes": [
                {"id": "input", "kind": "source", "component": "source.aligned"},
                *(
                    {"id": key, "kind": "transform", "component": component}
                    | {"params": params}
                    for key, component, params in steps
                ),
                {
                    "id": "model",
                    "kind": "detector",
                    "component": "detector:aberrant_moving_mahalanobis_distance",
                },
                {"id": "policy", "kind": "policy", "component": "policy.quantile"},
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


def recipes(definition, node):
    """name: (the feature it continues, the steps that changed it)."""
    return {
        item.name: (item.previous, item.steps)
        for item in compile_pipeline(definition).features[node]
    }


def test_each_feature_names_the_steps_that_changed_it_and_where_it_came_from():
    definition = chain(
        ("smooth", "prepare.smooth", {"apply_to": ["a"]}),
        ("change", "prepare.change", {"apply_to": ["b"]}),
        ("power", "prepare.formula", {"expression": "a * b", "name": "power"}),
        ("renamed", "features.rename", {"mapping": {"c": "cable"}}),
        ("scale", "adaptive.standard_scaler", {"apply_to": ["a", "power"]}),
    )
    assert recipes(definition, "input") == {
        "a": (None, []),
        "b": (None, []),
        "c": (None, []),
    }
    assert recipes(definition, "scale") == {
        "a": ("renamed.a", ["smooth", "scale"]),
        "b": ("renamed.b", []),
        # Renaming counts as a change, so the recipe shows where the name came from.
        "cable": ("renamed.cable", ["renamed"]),
        # An added feature continues the one it was computed from.
        "b_diff1": ("renamed.b_diff1", ["change"]),
        "power": ("renamed.power", ["power", "scale"]),
    }
    # Following previous back leads to where each feature was made.
    features = compile_pipeline(definition).features
    assert features["change"][3].previous == "smooth.b"
    assert features["renamed"][2].previous == "power.c"
    # A formula's feature is made from several, so it continues none of them.
    assert features["power"][-1].previous is None


def test_replacing_features_keeps_their_lineage_and_components_start_their_own():
    combined = recipes(
        chain(
            (
                "hottest",
                "prepare.aggregate",
                {"function": "max", "result": "replace", "apply_to": ["b", "c"]},
            ),
        ),
        "hottest",
    )
    assert combined == {"a": ("input.a", []), "max": (None, ["hottest"])}
    definition = branched()
    projected = compile_pipeline(definition).features["merge"]
    assert [(item.name, item.previous, item.steps) for item in projected] == [
        ("projection.component_1", "projection.projection.component_1", ["projection"]),
        ("temperature", "raw.temperature", []),
    ]


def test_the_report_says_when_each_prepare_step_has_its_first_output():
    definition = chain(
        ("smooth", "prepare.smooth", {"window_size": 10}),
        ("gate", "prepare.gate", {"condition": "a > 1"}),
        ("change", "prepare.change", {"apply_to": ["b"], "lag": 2}),
        ("scale", "adaptive.standard_scaler", {}),
    )
    report = bounded_validation_report(validate_pipeline(definition))
    assert report.ready_after == {"smooth": 10, "gate": 10, "change": 12}
    assert report.preparation_observations == 11
    # Designs without Prepare steps, and invalid ones, report none.
    plain = chain(("scale", "adaptive.standard_scaler", {}))
    assert bounded_validation_report(validate_pipeline(plain)).ready_after == {}
    broken = chain(("gate", "prepare.gate", {"condition": "a >"}))
    assert bounded_validation_report(validate_pipeline(broken)).ready_after == {}


@pytest.mark.parametrize(
    ("expression", "message", "fix"),
    [
        (
            "dc_current * sqr(dc_current)",
            "Unknown function sqr at character 14. Did you mean sqrt?",
            (13, 16, "sqrt"),
        ),
        (
            "`dc-votage` + 1",
            "Unknown feature dc-votage at character 1. Did you mean dc-voltage?",
            (0, 11, "`dc-voltage`"),
        ),
        ("1 + dc_curent", None, (4, 13, "dc_current")),
    ],
)
def test_a_suggestion_comes_with_the_text_that_applies_it(expression, message, fix):
    definition = chain(
        ("formula", "prepare.formula", {"expression": expression}),
        slots=("dc-voltage", "dc_current"),
    )
    issue = bounded_validation_report(validate_pipeline(definition)).issues[0]
    if message:
        assert issue.message == message
    assert issue.parameter_path == ["expression"]
    assert (issue.fix.start, issue.fix.end, issue.fix.text) == fix
    fixed = expression[: fix[0]] + fix[2] + expression[fix[1] :]
    parse(fixed).check_names(["dc-voltage", "dc_current"])


def test_problems_without_a_suggestion_offer_no_fix():
    definition = chain(("gate", "prepare.gate", {"condition": "zzz > 1"}))
    issue = bounded_validation_report(validate_pipeline(definition)).issues[0]
    assert issue.message == "Unknown feature zzz at character 1."
    assert issue.fix is None
    with pytest.raises(FormulaError) as raised:
        parse("a +")
    assert raised.value.fix is None


@pytest.mark.parametrize(
    ("name", "text"),
    [("power", "power"), ("_x1", "_x1"), ("and", "`and`"), ("dc-v", "`dc-v`")],
)
def test_names_are_written_as_a_formula_reads_them(name, text):
    assert written(name) == text
    assert parse(text).names == (name,)


def test_a_name_with_a_backtick_cannot_be_written():
    assert written("a`b") is None
