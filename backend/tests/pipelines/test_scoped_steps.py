"""Applies to and Result on learned steps, robust scaling and issue severity."""

import pickle

import numpy as np
import pytest
from off_key_core.models import pipeline_compiler
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    pipeline_catalog,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.batch import BatchFeatureGraph
from off_key_mqtt_radar.pipelines.components import ScopedStep
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources

from tests.support.pipelines import branched

pytestmark = pytest.mark.radar_integration

SLOTS = ("a", "b", "temperature")
DETECTORS = {
    "static_baseline": ("detector:pyod_iforest", {"n_estimators": 10}),
    "adaptive_stream": ("detector:aberrant_moving_mahalanobis_distance", {}),
}
POLICIES = {
    "static_baseline": "policy.martingale",
    "adaptive_stream": "policy.quantile",
}


def definition(strategy, steps, edges, *, last):
    detector, params = DETECTORS[strategy]
    return PipelineDefinition.model_validate(
        {
            "strategy": strategy,
            "input_slots": [{"id": slot, "label": slot.title()} for slot in SLOTS],
            "nodes": [
                {"id": "input", "kind": "source", "component": "source.aligned"},
                *steps,
                {
                    "id": "model",
                    "kind": "detector",
                    "component": detector,
                    "params": params,
                },
                {"id": "policy", "kind": "policy", "component": POLICIES[strategy]},
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


def plumbing(strategy, scaler, projection=None):
    """Today's way to process some features: select, process, merge the rest back."""
    steps = [
        {
            "id": "used",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["a", "b"]},
        },
        {"id": "scale", "kind": "transform", "component": scaler},
        {
            "id": "raw",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["temperature"]},
        },
        {"id": "joined", "kind": "merge", "component": "features.merge"},
    ]
    edges = [
        {"source": "input", "target": "used"},
        {"source": "used", "target": "scale"},
        {"source": "input", "target": "raw"},
        {"source": "raw", "target": "joined", "order": 1},
    ]
    processed = "scale"
    if projection is not None:
        component, params = projection
        steps.append(
            {"id": "pca", "kind": "transform", "component": component, "params": params}
        )
        edges.append({"source": "scale", "target": "pca"})
        processed = "pca"
    edges.append({"source": processed, "target": "joined", "order": 0})
    return definition(strategy, steps, edges, last="joined")


def scoped(strategy, scaler, projection=None, **scale):
    """The same processing as scoped steps on one chain."""
    steps = [
        {
            "id": "scale",
            "kind": "transform",
            "component": scaler,
            "params": {"apply_to": ["a", "b"], **scale},
        }
    ]
    edges = [{"source": "input", "target": "scale"}]
    last = "scale"
    if projection is not None:
        component, params = projection
        steps.append(
            {
                "id": "pca",
                "kind": "transform",
                "component": component,
                "params": {**params, "apply_to": ["a", "b"]},
            }
        )
        edges.append({"source": "scale", "target": "pca"})
        last = "pca"
    return definition(strategy, steps, edges, last=last)


def bound(design):
    compiled = compile_pipeline(design).definition
    bindings = [
        BoundInput(
            slot_id=slot,
            reading_id=f"reading-{slot}",
            entity_id="charger",
            accepted_topic=f"telemetry/charger/{slot}",
            input_key=f"reading_{slot}",
        )
        for slot in SLOTS
    ]
    return ExecutionPlan(
        PipelineExecutionConfig(
            definition=compiled,
            bindings=bindings,
            run_id="run",
            revision_id="revision",
            fingerprint=execution_fingerprint(compiled, bindings),
        )
    )


ROWS = [
    {"a": float(index), "b": float(index * index % 7), "temperature": 20.0 + index % 5}
    for index in range(1, 31)
]


def features(design):
    return compile_pipeline(design).features


# Fingerprints of the bundled templates and the shared fixtures, recorded before
# scope settings existed. Scope settings at their defaults must never change them.
PINNED = {
    ("template", "static_baseline"): (
        "a7b976c0d7beb1cce6651a92fc8e1644abb9dba949979faebaa4ed87b23f59ad"
    ),
    ("template", "adaptive_stream"): (
        "f426b2a42b030cae83e08b4934bf196fdcfa5676723af2228aca4596777de78b"
    ),
    ("branched", "static_baseline"): (
        "9b7ed493e229e4cd1f5e99ad4307031af96dd461238a0ebbe6f86331cd86caa0"
    ),
    ("branched", "adaptive_stream"): (
        "2cefaedbf39a859de2f10463607956faf0109258a6211dbeb2443dc7dd330393"
    ),
}


@pytest.mark.parametrize(("fixture", "strategy"), sorted(PINNED))
def test_designs_without_scope_keep_their_fingerprints(fixture, strategy):
    design = (
        next(
            item.definition
            for item in pipeline_catalog().templates
            if item.id == strategy
        )
        if fixture == "template"
        else branched(strategy)
    )
    result = compile_pipeline(design)
    assert result.fingerprint == PINNED[fixture, strategy]
    for node in result.definition.nodes:
        assert not {"apply_to", "result", "suffix"} & set(node.params)


def test_scope_settings_at_their_defaults_are_left_out_of_the_fingerprint():
    plain = plumbing("adaptive_stream", "adaptive.standard_scaler")
    spelled = plain.model_copy(deep=True)
    scale = next(node for node in spelled.nodes if node.id == "scale")
    # A suffix only names added features, so it means nothing while replacing.
    scale.params = {"apply_to": None, "result": "replace", "suffix": "z"}
    assert compile_pipeline(spelled).fingerprint == compile_pipeline(plain).fingerprint
    scale.params = {"result": "add"}
    assert compile_pipeline(spelled).fingerprint != compile_pipeline(plain).fingerprint


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_replacing_some_features_keeps_positions_and_raw_bypass(strategy):
    family = "adaptive" if strategy == "adaptive_stream" else "static"
    columns = features(scoped(strategy, f"{family}.standard_scaler"))["scale"]
    assert [(item.name, item.slots, item.raw) for item in columns] == [
        ("a", ["a"], False),
        ("b", ["b"], False),
        ("temperature", ["temperature"], True),
    ]


def test_adding_features_appends_them_in_the_order_of_applies_to():
    design = scoped(
        "static_baseline",
        "static.min_max_scaler",
        apply_to=["b", "a"],
        result="add",
        clip=True,
    )
    columns = features(design)["scale"]
    assert [item.name for item in columns] == [
        "a",
        "b",
        "temperature",
        "b_minmax",
        "a_minmax",
    ]
    assert [item.raw for item in columns] == [True, True, True, False, False]
    assert (columns[3].minimum, columns[3].maximum) == (0.0, 1.0)
    renamed = scoped(
        "static_baseline", "static.min_max_scaler", result="add", suffix="unit"
    )
    assert [item.name for item in features(renamed)["scale"]][3:] == [
        "a_unit",
        "b_unit",
    ]


@pytest.mark.parametrize("result", ["replace", "add"])
def test_a_projection_uses_its_features_and_appends_components(result):
    design = scoped(
        "static_baseline",
        "static.standard_scaler",
        ("static.pca", {"n_components": 1, "result": result}),
    )
    columns = features(design)["pca"]
    kept = ["temperature"] if result == "replace" else ["a", "b", "temperature"]
    assert [item.name for item in columns] == [*kept, "pca.component_1"]
    assert columns[-1].slots == ["a", "b"]


@pytest.mark.parametrize(
    ("params", "code", "message", "path"),
    [
        (
            {"apply_to": ["a", "voltage"]},
            "scope",
            "voltage is not available at this step.",
            ["apply_to"],
        ),
        (
            {"result": "add", "suffix": "x"},
            "scope",
            "a_x already exists. Choose another suffix.",
            ["suffix"],
        ),
        (
            {"apply_to": ["a", "a"]},
            "parameters",
            "List each feature at most once",
            ["apply_to"],
        ),
        (
            {"result": "add", "suffix": "two words"},
            "parameters",
            "Use letters, digits and underscores.",
            ["suffix"],
        ),
    ],
)
def test_scope_errors_point_at_their_setting(params, code, message, path):
    design = definition(
        "static_baseline",
        [
            {
                "id": "taken",
                "kind": "transform",
                "component": "features.rename",
                "params": {"mapping": {"b": "a_x"}},
            },
            {
                "id": "scale",
                "kind": "transform",
                "component": "static.standard_scaler",
                "params": params,
            },
        ],
        [
            {"source": "input", "target": "taken"},
            {"source": "taken", "target": "scale"},
        ],
        last="scale",
    )
    result = validate_pipeline(design)
    assert not result.valid and result.fingerprint is None
    issue = next(item for item in result.issues if item.node_id == "scale")
    assert (issue.code, issue.message, issue.parameter_path, issue.severity) == (
        code,
        message,
        path,
        "error",
    )


def test_a_projection_cannot_have_more_components_than_features_it_uses():
    design = scoped(
        "static_baseline",
        "static.standard_scaler",
        ("static.pca", {"n_components": 3}),
    )
    issue = next(
        item for item in validate_pipeline(design).issues if item.node_id == "pca"
    )
    assert issue.message == "n_components must not exceed the 2 features it uses"


def test_warnings_are_shown_without_blocking_a_design(monkeypatch):
    def review(compilation):
        compilation.warning("review", "Look at this step", "model")

    monkeypatch.setattr(pipeline_compiler, "_validate_model", review)
    result = compile_pipeline(plumbing("static_baseline", "static.standard_scaler"))
    assert result.valid and result.fingerprint
    assert [(item.code, item.severity) for item in result.issues] == [
        ("review", "warning")
    ]


@pytest.mark.parametrize(
    ("scaler", "projection"),
    [
        ("static.standard_scaler", None),
        ("static.robust_scaler", None),
        ("static.standard_scaler", ("static.pca", {"n_components": 1})),
    ],
)
def test_static_scoped_steps_equal_selecting_and_merging(scaler, projection):
    outputs = []
    for design in (plumbing, scoped):
        plan = bound(design("static_baseline", scaler, projection))
        graph = BatchFeatureGraph(plan)
        names = plan.names(plan.source_id)
        rows = np.array([[row[name] for name in names] for row in ROWS])
        fitted = graph.fit_transform(rows[:20])
        later = graph.transform(rows[20:])
        outputs.append(
            {
                name: (fitted[:, index], later[:, index])
                for index, name in enumerate(plan.output_features)
            }
        )
    plain, scope = outputs
    assert plain.keys() == scope.keys()
    for name, (fitted, later) in plain.items():
        np.testing.assert_allclose(scope[name][0], fitted)
        np.testing.assert_allclose(scope[name][1], later)


def _stream(plan):
    """Score before learning, recording the features the detector learns from."""
    learned = []

    def observe(item):
        if item.node_id == "$model" and item.phase == "learn":
            learned.append(dict(item.inputs))

    graph, _ = adaptive_graph(plan, observer=observe)
    scores = []
    for row in ROWS:
        values = plan.bind({f"reading_{key}": value for key, value in row.items()})
        if graph.readiness.ready:
            scores.append(graph.score_one(values))
        graph.learn_one(values)
    return graph, learned, scores


@pytest.mark.parametrize(
    ("scaler", "params", "projection"),
    [
        ("adaptive.standard_scaler", {}, None),
        ("adaptive.robust_scaler", {"min_samples": 3}, None),
        (
            "adaptive.standard_scaler",
            {},
            ("adaptive.uncentered_pca", {"n_components": 1, "n0": 3}),
        ),
    ],
)
def test_adaptive_scoped_steps_equal_selecting_and_merging(scaler, params, projection):
    plain_design = plumbing("adaptive_stream", scaler, projection)
    if params:
        next(node for node in plain_design.nodes if node.id == "scale").params = params
    _, plain, plain_scores = _stream(bound(plain_design))
    graph, scope, scope_scores = _stream(
        bound(scoped("adaptive_stream", scaler, projection, **params))
    )
    assert len(plain) == len(scope) > 20
    for expected, actual in zip(plain, scope, strict=True):
        assert actual.keys() == expected.keys()
        assert actual == pytest.approx(expected)
    # The detector is invariant to feature order, so scores agree too.
    assert scope_scores == pytest.approx(plain_scores)
    assert isinstance(graph.nodes[0].transformer, ScopedStep)
    restored = pickle.loads(pickle.dumps(graph))
    values = bound(scoped("adaptive_stream", scaler, projection, **params)).bind(
        {"reading_a": 4.0, "reading_b": 9.0, "reading_temperature": 21.0}
    )
    assert restored.score_one(values) == pytest.approx(graph.score_one(values))


def test_unscoped_adaptive_steps_keep_their_plain_runtime_shape():
    graph, _, _ = _stream(
        bound(plumbing("adaptive_stream", "adaptive.standard_scaler"))
    )
    assert not any(
        isinstance(getattr(node, "transformer", None), ScopedStep)
        for node in graph.nodes
    )


def test_both_strategies_scale_by_the_same_median_and_interquartile_range():
    training = ROWS[:20]
    later = ROWS[20]
    static_plan = bound(scoped("static_baseline", "static.robust_scaler"))
    batch = BatchFeatureGraph(static_plan)
    names = static_plan.names(static_plan.source_id)
    batch.fit_transform(np.array([[row[name] for name in names] for row in training]))
    expected = batch.transform(np.array([[later[name] for name in names]]))[0]
    adaptive_plan = bound(
        scoped("adaptive_stream", "adaptive.robust_scaler", min_samples=3)
    )
    step = adaptive_graph(adaptive_plan)[0].nodes[0].transformer
    for row in training:
        step.learn_one(row)
    actual = step.transform_one(later)
    assert list(actual) == names
    assert [actual[name] for name in names] == pytest.approx(list(expected))


def test_resources_count_only_the_features_a_step_keeps_state_for():
    design = scoped(
        "adaptive_stream",
        "adaptive.robust_scaler",
        ("adaptive.uncentered_pca", {"n_components": 1, "n0": 3}),
        window_size=100,
        min_samples=3,
    )
    report = estimate_resources(bound(design), 4096)
    wider = scoped(
        "adaptive_stream",
        "adaptive.robust_scaler",
        ("adaptive.uncentered_pca", {"n_components": 1, "n0": 3}),
        window_size=200,
        min_samples=3,
    )
    larger = estimate_resources(bound(wider), 4096)
    # Two features with 100 retained floats each, then twice the window.
    assert report.projection_state_numeric_bytes > 2 * 100 * 24
    assert larger.projection_state_numeric_bytes > report.projection_state_numeric_bytes
