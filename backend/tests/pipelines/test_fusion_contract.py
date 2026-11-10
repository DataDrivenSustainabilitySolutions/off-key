"""Designs whose policy combines up to four detectors: compiler and settings."""

import pytest
from off_key_core.models.pipelines import (
    derive_monitoring_config,
    pipeline_components,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import PipelineDefinition

from tests.support.fused_pipeline import fused_definition
from tests.support.pipelines import template


def _issues(definition):
    return [
        (issue.code, issue.node_id, issue.message)
        for issue in validate_pipeline(definition).issues
    ]


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_two_detectors_compile_with_one_input_each_to_the_policy(strategy):
    result = validate_pipeline(fused_definition(strategy))

    assert result.valid, result.issues
    assert result.detector_ids == ["detector", "detector_2"]
    assert result.detector_inputs == {"detector": "only_a", "detector_2": "only_b"}
    assert [item.name for item in result.features["detector"]] == ["a"]
    assert [item.name for item in result.features["detector_2"]] == ["b"]
    # Scores arrive at the policy, one per detector; no feature goes further.
    assert result.features["policy"] == result.features["output"] == []


def test_four_detectors_are_the_most_a_policy_combines():
    assert validate_pipeline(fused_definition(detectors=4)).valid
    data = fused_definition(detectors=4).model_dump(mode="json")
    data["nodes"].append(
        {"id": "detector_5", "kind": "detector", "component": "detector:pyod_knn"}
    )
    data["edges"] += [
        {"source": "scale", "target": "detector_5"},
        {"source": "detector_5", "target": "policy", "order": 4},
    ]

    assert (
        "node_count",
        None,
        "A design can combine at most 4 detectors; this one has 5.",
    ) in _issues(PipelineDefinition.model_validate(data))


def test_a_design_needs_a_detector():
    data = template("static_baseline").model_dump(mode="json")
    data["nodes"] = [node for node in data["nodes"] if node["kind"] != "detector"]
    data["edges"] = [
        edge
        for edge in data["edges"]
        if "detector" not in (edge["source"], edge["target"])
    ]

    assert (
        "node_count",
        None,
        "An executable design requires at least one detector node",
    ) in _issues(PipelineDefinition.model_validate(data))


def test_every_detector_connects_to_the_calibration_step():
    data = fused_definition().model_dump(mode="json")
    data["edges"] = [edge for edge in data["edges"] if edge["source"] != "detector_2"]

    issues = _issues(PipelineDefinition.model_validate(data))

    assert (
        "input_count",
        "calibrate",
        "calibration requires one incoming connection from each of the 2 detectors",
    ) in issues
    assert (
        "disconnected",
        "detector_2",
        "Every node must reach the evidence output",
    ) in issues


def test_combine_is_left_out_at_its_default_and_with_one_detector():
    strongest = validate_pipeline(fused_definition(fusion="max"))
    default = validate_pipeline(fused_definition())
    average = validate_pipeline(fused_definition(fusion="mean"))
    # The calibration step holds the setting; the schema 1 form keeps it on
    # the policy, as the editor knows it.
    calibration = {node.id: node for node in average.definition.nodes}["calibrate"]
    policy = next(
        node
        for node in average.definition.model_dump()["nodes"]
        if node["id"] == "policy"
    )

    assert strongest.fingerprint == default.fingerprint != average.fingerprint
    assert calibration.params["fusion"] == "mean"
    assert policy["params"]["fusion"] == "mean"
    assert not any("fusion" in node.params for node in default.definition.nodes)
    # One detector has nothing to combine, so the setting does not change it.
    single = template("adaptive_stream").model_dump(mode="json")
    plain = validate_pipeline(PipelineDefinition.model_validate(single))
    next(node for node in single["nodes"] if node["kind"] == "policy")["params"] = {
        "fusion": "mean"
    }
    combined = validate_pipeline(PipelineDefinition.model_validate(single))
    assert combined.valid and combined.fingerprint == plain.fingerprint


def test_combine_accepts_strongest_or_average_only():
    issues = _issues(fused_definition(fusion="median"))

    assert [(code, node) for code, node, _ in issues] == [("parameters", "calibrate")]


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_run_settings_hold_the_first_detector_and_the_policy_without_combine(
    strategy,
):
    monitoring = derive_monitoring_config(fused_definition(strategy, fusion="mean"))

    assert monitoring.model_type == (
        "pyod_iforest"
        if strategy == "static_baseline"
        else "aberrant_moving_average_absolute_deviation"
    )
    policy = (
        monitoring.martingale_config
        if strategy == "static_baseline"
        else monitoring.threshold_config
    )
    assert "fusion" not in policy.model_dump()


def test_every_calibration_step_offers_combine_in_the_catalog():
    components = pipeline_components()
    for component in components:
        names = [item.name for item in component.fields]
        if component.kind != "calibration":
            # The calibration step combines detectors; no policy does.
            assert "fusion" not in names
            continue
        field = next(item for item in component.fields if item.name == "fusion")
        assert (field.label, field.type, field.options, field.default) == (
            "Combine detectors",
            "enum",
            ["max", "mean"],
            "max",
        )


def test_each_adaptive_detector_checks_its_own_features():
    data = fused_definition("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in data["nodes"] if node["id"] == "detector_2")
    detector["component"] = "detector:aberrant_moving_covariance"
    detector["params"] = {"window_size": 5}

    issues = _issues(PipelineDefinition.model_validate(data))

    assert [(code, node) for code, node, _ in issues] == [
        ("model_features", "detector_2")
    ]
