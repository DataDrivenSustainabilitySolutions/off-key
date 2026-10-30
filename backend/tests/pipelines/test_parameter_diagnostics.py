"""Real catalog metadata and machine locations across both authoring surfaces."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.v1.monitors import _normalize_models_for_gateway
from off_key_core.models.parameter_validation import validate_parameter_schema
from off_key_core.models.pipeline_fields import component_fields
from off_key_core.models.pipelines import pipeline_catalog, validate_pipeline
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_tactic_middleware.api.v1.models import router
from off_key_tactic_middleware.services.pipelines.release import normalize_saved_launch
from pydantic import ValidationError

from tests.support.form_pipeline import form_launch

pytestmark = pytest.mark.radar_integration


def test_reviewed_1_3_launch_normalization_preserves_history_and_execution():
    launch = form_launch(
        container_name="reviewed-migration",
        strategy="adaptive_stream",
        mqtt_topics=["telemetry/entity/x"],
        model_type="aberrant_moving_average",
        adaptive_stream_config={
            "model_type": "aberrant_moving_average",
            "model_params": {"window_size": 8},
            "training_window_size": 2,
            "calibration_window_size": 3,
        },
    )
    saved = launch.model_dump(mode="json")
    saved["monitoring"]["aberrant_version"] = "1.3.0"
    original = deepcopy(saved)
    normalized = normalize_saved_launch(saved)
    assert saved == original
    assert normalized.monitoring.aberrant_version == "1.4.0"
    assert normalized.pipeline == launch.pipeline
    assert normalized.runtime_image is None


def test_pydantic_variant_diagnostics_address_submitted_object_keys():
    definition = next(
        item.definition.model_copy(deep=True)
        for item in pipeline_catalog().templates
        if item.definition.strategy == "static_baseline"
    )
    policy = next(node for node in definition.nodes if node.kind == "policy")
    policy.params = {
        "trackers": [
            {
                "tracker_id": "primary",
                "betting_function": "power",
                "threshold_config": {"mode": "manual", "value": 0},
            }
        ]
    }
    result = validate_pipeline(definition)
    paths = [
        issue.parameter_path for issue in result.issues if issue.node_id == policy.id
    ]
    assert ["trackers", 0, "threshold_config", "value"] in paths
    assert all("manual" not in path and "power" not in path for path in paths if path)


def test_discovery_serves_the_graphs_actual_fields_without_numerical_imports():
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/models/")
    assert response.status_code == 200
    models = _normalize_models_for_gateway(response.json())
    components = {item.id: item for item in pipeline_catalog().components}
    for name, model in models.items():
        assert model["fields"] == [
            field.model_dump(mode="json")
            for field in components[f"detector:{name}"].fields
        ]
    engine = next(
        field
        for field in models["aberrant_knn"]["fields"]
        if field["name"] == "similarity_engine"
    )
    assert engine["type"] == "component"
    assert {field["name"] for field in engine["fields"]} == {"window_size", "warm_up"}


def test_fields_distinguish_missing_default_explicit_null_and_exclusive_bounds():
    fields = component_fields(
        {
            "type": "object",
            "required": ["required"],
            "properties": {
                "required": {"type": "number", "exclusiveMinimum": 0},
                "optional": {"type": "integer", "maximum": 10},
                "nullable": {
                    "anyOf": [{"type": "number"}, {"type": "null"}],
                    "default": None,
                },
                "bounded": {"type": "number", "minimum": 0, "exclusiveMaximum": 1},
            },
        }
    )
    required, optional, nullable, bounded = fields
    assert required.required and not required.has_default
    assert required.minimum is None and required.exclusive_minimum == 0
    assert not optional.required and not optional.has_default
    assert nullable.nullable and nullable.has_default and nullable.default is None
    assert (
        bounded.minimum == 0
        and bounded.maximum is None
        and bounded.exclusive_maximum == 1
    )


def test_schema_locations_include_missing_and_unexpected_fields():
    with pytest.raises(ValidationError) as error:
        validate_parameter_schema(
            "parameters",
            {
                "type": "object",
                "required": ["a", "b"],
                "properties": {"a": {"type": "integer"}, "b": {"type": "number"}},
                "additionalProperties": False,
            },
            {"a": False, "extra": 1},
        )
    assert {(issue["type"], issue["loc"]) for issue in error.value.errors()} == {
        ("invalid_type", ("a",)),
        ("missing_parameter", ("b",)),
        ("unexpected_parameter", ("extra",)),
    }


def test_independent_missing_fields_are_reported_once_each():
    with pytest.raises(ValidationError) as error:
        validate_parameter_schema(
            "parameters",
            {"type": "object", "required": ["a", "b"]},
            {},
        )
    assert [(issue["loc"], issue["msg"]) for issue in error.value.errors()] == [
        (("a",), "'a' is a required property"),
        (("b",), "'b' is a required property"),
    ]


def test_nested_adaptive_form_and_graph_keep_all_field_locations():
    params = {
        "k": "many",
        "similarity_engine": {
            "id": "faiss",
            "params": {
                "window_size": False,
                "warm_up": "many",
            },
        },
    }
    with pytest.raises(ValidationError) as error:
        AdaptiveStreamConfig(model_type="aberrant_knn", model_params=params)
    expected = {
        ("k",),
        ("similarity_engine", "params", "window_size"),
        ("similarity_engine", "params", "warm_up"),
    }
    assert {issue["loc"] for issue in error.value.errors()} == {
        ("model_params", *path) for path in expected
    }
    definition = next(
        item.definition.model_copy(deep=True)
        for item in pipeline_catalog().templates
        if item.definition.strategy == "adaptive_stream"
    )
    node = next(node for node in definition.nodes if node.kind == "detector")
    node.component = "detector:aberrant_knn"
    node.params = params
    result = validate_pipeline(definition)
    assert not result.valid
    assert {
        tuple(issue.parameter_path)
        for issue in result.issues
        if issue.node_id == node.id and issue.parameter_path is not None
    } == expected
