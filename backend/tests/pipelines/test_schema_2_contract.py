"""Schema 2 designs: no lane, a calibration step, and checks by learning mode.

Schema 1 designs are read as schema 2 and written back unchanged, so stored
designs, the editor's wire format and fingerprints stay as they were.
"""

import pytest
from off_key_core.models.pipeline_catalog import editor_components
from off_key_core.models.pipelines import pipeline_components, validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition

from tests.support.fused_pipeline import fused_definition
from tests.support.pipelines import template

SOURCE = {"id": "input", "kind": "source", "component": "source.aligned"}
OUTPUT = {"id": "output", "kind": "output", "component": "output.evidence"}
IFOREST = "detector:pyod_iforest"
MAD = "detector:aberrant_moving_average_absolute_deviation"


def design(*detectors, policy="policy.quantile", scaler=None):
    """A schema 2 design: each detector reads the input, all feed one fixed split."""
    nodes = [dict(SOURCE)]
    edges = []
    for index, component in enumerate(detectors, start=1):
        identifier = f"detector_{index}"
        params = {"window_size": 10} if component == MAD else {"n_estimators": 10}
        nodes.append(
            {
                "id": identifier,
                "kind": "detector",
                "component": component,
                "params": params,
            }
        )
        reads = "input"
        if scaler is not None and index == 1:
            nodes.append({"id": "scale", "kind": "transform", "component": scaler})
            edges.append({"source": "input", "target": "scale"})
            reads = "scale"
        edges.append({"source": reads, "target": identifier})
        edges.append({"source": identifier, "target": "calibrate", "order": index - 1})
    nodes += [
        {
            "id": "calibrate",
            "kind": "calibration",
            "component": "calibrate.fixed_split",
        },
        {"id": "policy", "kind": "policy", "component": policy},
        dict(OUTPUT),
    ]
    edges += [
        {"source": "calibrate", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(
        {
            "schema_version": 2,
            "input_slots": [{"id": "a", "label": "A"}],
            "nodes": nodes,
            "edges": edges,
            "settings": {"training_window_size": 30, "calibration_window_size": 20},
        }
    )


def issues(definition):
    return [(item.code, item.node_id) for item in validate_pipeline(definition).issues]


@pytest.mark.parametrize(
    "definition",
    [
        template("static_baseline"),
        template("adaptive_stream"),
        fused_definition("static_baseline", fusion="mean"),
        fused_definition("adaptive_stream", fusion="mean", quantile=0.99),
    ],
)
def test_schema_1_designs_are_written_back_unchanged(definition):
    stored = definition.model_dump(mode="json")
    read = PipelineDefinition.model_validate(stored)

    assert stored["schema_version"] == 1 and "calibration" not in {
        node["kind"] for node in stored["nodes"]
    }
    assert [node.kind for node in read.nodes].count("calibration") == 1
    assert read.model_dump(mode="json") == stored


def test_a_schema_1_policy_reads_its_detectors_through_a_fixed_split():
    read = PipelineDefinition.model_validate(
        fused_definition("static_baseline", fusion="mean").model_dump(mode="json")
    )
    nodes = {node.id: node for node in read.nodes}
    into = sorted(edge.source for edge in read.edges if edge.target == "calibrate")

    assert nodes["calibrate"].component == "calibrate.fixed_split"
    assert nodes["calibrate"].params == {"fusion": "mean"}
    assert "fusion" not in nodes["policy"].params
    assert into == ["detector", "detector_2"]
    assert [edge.source for edge in read.edges if edge.target == "policy"] == [
        "calibrate"
    ]


def test_a_schema_2_design_of_one_lane_has_the_schema_1_fingerprint():
    native = validate_pipeline(design(MAD, MAD))
    legacy = validate_pipeline(
        PipelineDefinition.model_validate(native.definition.model_dump(mode="json"))
    )

    assert native.valid, native.issues
    assert native.definition.model_dump(mode="json")["strategy"] == "adaptive_stream"
    assert native.fingerprint == legacy.fingerprint


def test_a_schema_2_design_needs_a_calibration_step():
    data = {
        "schema_version": 2,
        "input_slots": [{"id": "a", "label": "A"}],
        "nodes": [
            SOURCE,
            {
                "id": "detector",
                "kind": "detector",
                "component": MAD,
                "params": {"window_size": 10},
            },
            {"id": "policy", "kind": "policy", "component": "policy.quantile"},
            OUTPUT,
        ],
        "edges": [
            {"source": "input", "target": "detector"},
            {"source": "detector", "target": "policy"},
            {"source": "policy", "target": "output"},
        ],
    }
    found = issues(PipelineDefinition.model_validate(data))

    assert ("node_count", None) in found
    assert ("port_type", "policy") in found


def test_a_detector_reads_steps_that_learn_as_it_does():
    found = issues(
        design(IFOREST, policy="policy.martingale", scaler="adaptive.standard_scaler")
    )

    assert ("learning", "scale") in found
    assert (
        issues(
            design(IFOREST, policy="policy.martingale", scaler="static.standard_scaler")
        )
        == []
    )


def test_detectors_that_learn_differently_wait_for_the_shared_runtime():
    found = issues(design(IFOREST, MAD))

    assert ("learning_mix", None) in found
    assert all(code != "port_type" for code, _ in found)


def test_the_martingale_needs_detectors_that_stop_learning():
    assert ("calibration", "policy") in issues(design(MAD, policy="policy.martingale"))
    assert issues(design(IFOREST, policy="policy.martingale")) == []


def test_a_policy_runs_only_where_its_detectors_learn():
    found = issues(design(IFOREST, policy="policy.quantile"))

    assert ("strategy", "policy") in found
    assert issues(design(MAD, policy="policy.quantile")) == []


def test_every_detector_gives_scores_and_the_calibration_step_p_values():
    components = {item.id: item for item in pipeline_components()}

    assert {
        item.output_type for item in components.values() if item.kind == "detector"
    } == {"scores"}
    assert {
        item.learning for item in components.values() if item.kind == "detector"
    } == {"batch", "online"}
    fixed = components["calibrate.fixed_split"]
    assert (fixed.input_type, fixed.output_type) == ("scores", "p_values")
    assert {
        components[identifier].input_type
        for identifier in ("policy.martingale", "policy.quantile")
    } == {"p_values"}


def test_the_editor_catalog_keeps_schema_1_ports_until_it_shows_calibration():
    editor = {item.id: item for item in editor_components()}

    assert "calibrate.fixed_split" not in editor
    assert editor[IFOREST].output_type == "p_values"
    assert editor["policy.quantile"].input_type == "scores"
    assert editor["policy.martingale"].input_type == "p_values"
