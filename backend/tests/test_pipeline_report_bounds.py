"""Real compilation and HTTP JSON bounds at the admitted graph limits."""

import json
import tracemalloc

import pytest
from fastapi.encoders import jsonable_encoder
from off_key_core.models.pipeline_reports import (
    MAX_PIPELINE_REPORT_BYTES,
    bounded_validation_report,
)
from off_key_core.models.pipelines import (
    compile_pipeline,
    pipeline_catalog,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.utils.json_budget import fits_json_budget
from starlette.responses import JSONResponse

pytestmark = pytest.mark.radar_integration


def maximum_definition():
    definition = pipeline_catalog().templates[1].definition.model_dump(mode="json")
    definition["input_slots"] = [
        {"id": f"slot_{index:03}" + "x" * 92, "label": f"Reading {index}"}
        for index in range(100)
    ]
    previous = "input"
    edges = []
    for index in range(60):
        identifier = f"p{index:02}_" + "x" * 96
        definition["nodes"].append(
            {
                "id": identifier,
                "kind": "transform",
                "component": "adaptive.random_projection",
                "params": {"n_components": 100},
            }
        )
        edges.append({"source": previous, "target": identifier})
        previous = identifier
    definition["edges"] = [
        *edges,
        {"source": previous, "target": "detector"},
        {"source": "detector", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(definition)


@pytest.fixture(scope="module")
def maximum_compilation():
    result = compile_pipeline(maximum_definition())
    assert len(result.definition.nodes) == 64
    assert all(len(columns) == 100 for columns in result.features.values())
    # Establish the expansion without ever serializing that 60+MiB payload.
    assert (
        sum(
            len(slot)
            for columns in result.features.values()
            for feature in columns
            for slot in feature.slots
        )
        > 60_000_000
    )
    return result


@pytest.mark.parametrize(
    "selected", ["input", "p00_" + "x" * 96, "p59_" + "x" * 96, "detector"]
)
def test_maximum_report_preserves_complete_selected_feature_choices(
    maximum_compilation, selected
):
    result = maximum_compilation
    tracemalloc.start()
    try:
        report = bounded_validation_report(result, selected)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024
    payload = JSONResponse(jsonable_encoder(report)).body
    assert len(payload) <= MAX_PIPELINE_REPORT_BYTES
    assert fits_json_budget(report, MAX_PIPELINE_REPORT_BYTES)
    assert report.valid and report.definition == result.definition
    assert report.fingerprint == result.fingerprint
    assert not report.features_complete and not report.provenance_complete
    assert "metadata_budget" in {issue.code for issue in report.issues}
    scope = [selected, *result.incoming[selected]]
    for identifier in scope:
        assert [
            feature.name for feature in report.features[identifier]
        ] == result.feature_names[identifier]
        assert all(not feature.slots for feature in report.features[identifier])
        assert [feature.raw for feature in report.features[identifier]] == [
            feature.raw for feature in result.features[identifier]
        ]
    assert len(result.features["detector"][0].slots) == 100


def test_normal_reports_preserve_full_metadata():
    result = compile_pipeline(pipeline_catalog().templates[1].definition)
    report = bounded_validation_report(result, "detector")
    assert report.features == result.features
    assert report.features_complete and report.provenance_complete
    assert not report.definition_omitted and not report.issues_truncated
    assert not report.issues


def test_unknown_selected_node_returns_no_stale_metadata(maximum_compilation):
    report = bounded_validation_report(maximum_compilation, "removed_node")
    assert report.features == {} and not report.features_complete
    assert report.selected_node_id == "removed_node"
    assert "selected_node" in {issue.code for issue in report.issues}
    assert len(JSONResponse(jsonable_encoder(report)).body) <= MAX_PIPELINE_REPORT_BYTES


def test_invalid_oversized_definition_and_multibyte_error_are_bounded():
    definition = pipeline_catalog().templates[1].definition.model_copy(deep=True)
    definition.nodes[0].params = {"😺" * 100_000: "unknown"}
    # Validate through the actual compiler; its original failure retains details.
    definition = PipelineDefinition.model_validate(definition.model_dump())
    result = validate_pipeline(definition)
    assert not result.valid
    assert "configuration_budget" in {issue.code for issue in result.issues}
    report = bounded_validation_report(result, "input")
    assert report.definition is None and report.definition_omitted
    assert report.issues_truncated
    assert all(len(issue.message.encode("utf-8")) <= 1024 for issue in report.issues)
    assert len(JSONResponse(jsonable_encoder(report)).body) <= MAX_PIPELINE_REPORT_BYTES
    with pytest.raises(ValueError, match="configuration budget"):
        compile_pipeline(definition)


@pytest.mark.parametrize(
    "value", [{"x": [1, "é", True, None]}, ["a", {"b": 2.5}], "x" * 1000]
)
def test_json_budget_matches_ascii_encoded_transport(value):
    size = len(json.dumps(value, separators=(",", ":"), ensure_ascii=True))
    assert fits_json_budget(value, size)
    assert not fits_json_budget(value, size - 1)
