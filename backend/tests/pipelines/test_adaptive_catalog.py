"""Catalog provenance, API metadata, and legacy configuration migration."""

import json

import pytest
from aberrant import __version__
from aberrant.catalog import DetectorConfig
from off_key_api_gateway.api.v1.monitors import detectors_by_type
from off_key_core.models import (
    ABERRANT_VERSION,
    ADAPTIVE_MODELS_BY_TYPE,
    validate_adaptive_model_params,
)
from off_key_core.models.adaptive import CATALOG
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.catalog import generate_catalog

from tests.support.pipelines import template


def test_generated_catalog_matches_pinned_runtime():
    assert ABERRANT_VERSION == __version__ == "1.5.0"
    assert generate_catalog() == CATALOG


@pytest.mark.parametrize(
    ("model_type", "legacy", "canonical"),
    [
        ("aberrant_stream_random_histogram_forest", {"max_bins": 8}, {"max_depth": 8}),
        (
            "aberrant_moving_geometric_average",
            {"absolute_values": True},
            {"absoluteValues": True},
        ),
        (
            "aberrant_knn",
            {"k": 3, "window_size": 20, "warm_up": 5},
            {
                "k": 3,
                "similarity_engine": {
                    "id": "faiss",
                    "params": {"window_size": 20, "warm_up": 5},
                },
            },
        ),
    ],
)
def test_legacy_and_canonical_parameters_have_the_same_fingerprint(
    model_type, legacy, canonical
):
    old = AdaptiveStreamConfig(model_type=model_type, model_params=legacy)
    new = AdaptiveStreamConfig(model_type=model_type, model_params=canonical)
    assert old.model_params == new.model_params
    assert DetectorConfig.from_mapping(old.detector_mapping(["x"])).fingerprint() == (
        DetectorConfig.from_mapping(new.detector_mapping(["x"])).fingerprint()
    )


@pytest.mark.parametrize(
    ("model_type", "params"),
    [
        ("aberrant_stream_random_histogram_forest", {"max_bins": 8, "max_depth": 9}),
        (
            "aberrant_knn",
            {"window_size": 20, "similarity_engine": {"id": "faiss", "params": {}}},
        ),
        (
            "aberrant_knn",
            {
                "similarity_engine": {
                    "id": "arbitrary_import",
                    "params": {"window_size": 20, "warm_up": 5},
                }
            },
        ),
        (
            "aberrant_knn",
            {
                "similarity_engine": {
                    "id": "faiss",
                    "params": {"window_size": 2_000_000, "warm_up": 5},
                }
            },
        ),
        ("aberrant_moving_average", {"abs_diff": False}),
        ("aberrant_moving_average", {"key": "unsubscribed_sensor"}),
        ("aberrant_online_isolation_forest", {"num_trees": 2001}),
        ("aberrant_online_isolation_forest", {"num_trees": True}),
        ("aberrant_online_isolation_forest", {"subsample": float("nan")}),
        ("aberrant_half_space_trees", {"n_trees": 2000, "height": 20}),
        ("aberrant_seasonal_residual_detector", {}),
        ("aberrant_seasonal_residual_detector", {"season_length": 1}),
        ("aberrant_seasonal_residual_detector", {"season_length": 24.5}),
        ("aberrant_seasonal_residual_detector", {"season_length": 600_000}),
        (
            "aberrant_seasonal_residual_detector",
            {"season_length": 24, "alpha": 0.8, "gamma": 0.3},
        ),
        (
            "aberrant_seasonal_residual_detector",
            {"season_length": 24, "residual_alpha": 0},
        ),
        ("aberrant_seasonal_residual_detector", {"season_length": 24, "key": "x"}),
        ("aberrant_holt_winters_forecaster", {}),
        ("aberrant_holt_winters_forecaster", {"season_length": 1}),
        ("aberrant_holt_winters_forecaster", {"season_length": 24, "lead": 0}),
        ("aberrant_holt_winters_forecaster", {"season_length": 24, "lead": 2000}),
        ("aberrant_holt_winters_forecaster", {"season_length": 24, "horizon": 3}),
        ("aberrant_holt_winters_forecaster", {"season_length": 24, "target": "x"}),
        ("aberrant_holt_winters_forecaster", {"season_length": 24, "score": "cqr"}),
        (
            "aberrant_holt_winters_forecaster",
            {"season_length": 24, "alpha": 0.8, "gamma": 0.3},
        ),
        ("aberrant_seasonal_naive_forecaster", {"season_length": 0}),
        ("aberrant_seasonal_naive_forecaster", {"model": {"id": "holt_winters"}}),
    ],
)
def test_configuration_rejects_conflicts_unsupported_components_and_resource_abuse(
    model_type, params
):
    with pytest.raises(ValueError):
        validate_adaptive_model_params(model_type, params)


def test_request_rejects_another_runtime_version():
    with pytest.raises(ValueError, match="requires Aberrant"):
        AdaptiveStreamConfig(aberrant_version="0.5.0")


def test_catalog_capabilities_reach_the_detector_listing():
    model_type = "aberrant_rolling_matrix_profile"
    payload = detectors_by_type("adaptive_stream")[model_type]
    assert payload["family"] == "adaptive_aberrant"
    assert payload["algorithm_family"] == "time_series"
    assert payload["catalog_id"] == "rolling_matrix_profile"
    assert payload["default_capabilities"]["feature_count"] == {
        "minimum": 1,
        "maximum": 1,
    }
    assert payload["available"] is True
    json.dumps(payload, allow_nan=False)


def test_seasonal_forecast_detector_needs_its_season_and_one_feature():
    model_type = "aberrant_seasonal_residual_detector"
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    assert definition["catalog_id"] == "seasonal_residual_detector"
    assert definition["parameter_schema"]["required"] == ["season_length"]
    assert "season_length" not in definition["default_parameters"]
    assert definition["bound_parameters"] == ["key"]
    assert definition["default_capabilities"]["feature_count"] == {
        "minimum": 1,
        "maximum": 1,
    }
    params = validate_adaptive_model_params(model_type, {"season_length": 24})
    assert params["season_length"] == 24
    assert params["normalize"] is True

    config = AdaptiveStreamConfig(model_type=model_type, model_params=params)
    assert config.validate_feature_schema(["x"]) == 1
    with pytest.raises(ValueError, match="exactly one feature"):
        config.validate_feature_schema(["x", "y"])
    mapping = config.detector_mapping(["x"])
    assert mapping["model"]["params"]["key"] == "x"
    assert DetectorConfig.from_mapping(mapping).capabilities().warmup.minimum == 48


def test_seasonal_forecast_detector_in_a_design_checks_its_season_and_features():
    data = template("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    detector["component"] = "detector:aberrant_seasonal_residual_detector"
    detector["params"] = {"season_length": 24}
    assert validate_pipeline(PipelineDefinition.model_validate(data)).valid

    data["input_slots"].append({"id": "second", "label": "Second"})
    issues = validate_pipeline(PipelineDefinition.model_validate(data)).issues
    assert ("model_features", detector["id"]) in [
        (issue.code, issue.node_id) for issue in issues
    ]

    data["input_slots"].pop()
    detector["params"] = {}
    issues = validate_pipeline(PipelineDefinition.model_validate(data)).issues
    assert detector["id"] in [issue.node_id for issue in issues]


@pytest.mark.parametrize(
    ("model_type", "forecaster_id", "provided", "forecaster_params", "warmup"),
    [
        (
            "aberrant_holt_winters_forecaster",
            "holt_winters",
            {"season_length": 24, "lead": 6},
            {"season_length": 24, "horizon": 6, "alpha": 0.2},
            53,
        ),
        (
            "aberrant_seasonal_naive_forecaster",
            "seasonal_naive",
            {},
            {"season_length": 1, "horizon": 1},
            2,
        ),
    ],
)
def test_forecaster_step_is_a_residual_detector_around_its_forecaster(
    model_type, forecaster_id, provided, forecaster_params, warmup
):
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    assert definition["catalog_id"] == "residual_detector"
    assert definition["forecaster_id"] == forecaster_id
    assert definition["algorithm_family"] == "forecast"
    assert definition["bound_parameters"] == ["target"]
    # The forecaster looks as far ahead as the lead, so a horizon is not asked for.
    assert not {"horizon", "model", "target"} & set(
        definition["parameter_schema"]["properties"]
    )
    assert definition["default_capabilities"]["feature_count"] == {
        "minimum": 1,
        "maximum": 1,
    }
    params = validate_adaptive_model_params(model_type, provided)
    assert (params["lead"], params["score"]) == (provided.get("lead", 1), "scaled")

    config = AdaptiveStreamConfig(model_type=model_type, model_params=params)
    with pytest.raises(ValueError, match="exactly one feature"):
        config.validate_feature_schema(["x", "y"])
    model = config.detector_mapping(["x"])["model"]
    assert model["id"] == "residual_detector"
    assert model["params"]["target"] == "x"
    assert model["params"]["lead"] == params["lead"]
    assert model["params"]["model"]["id"] == forecaster_id
    assert forecaster_params.items() <= model["params"]["model"]["params"].items()
    capabilities = DetectorConfig.from_mapping(
        config.detector_mapping(["x"])
    ).capabilities()
    assert capabilities.warmup.minimum == warmup


def test_forecaster_step_in_a_design_checks_its_settings_and_features():
    data = template("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    detector["component"] = "detector:aberrant_holt_winters_forecaster"
    detector["params"] = {"season_length": 24, "lead": 3}
    assert validate_pipeline(PipelineDefinition.model_validate(data)).valid

    data["input_slots"].append({"id": "second", "label": "Second"})
    issues = validate_pipeline(PipelineDefinition.model_validate(data)).issues
    assert ("model_features", detector["id"]) in [
        (issue.code, issue.node_id) for issue in issues
    ]

    data["input_slots"].pop()
    detector["params"] = {"lead": 3}
    issues = validate_pipeline(PipelineDefinition.model_validate(data)).issues
    assert detector["id"] in [issue.node_id for issue in issues]


def test_forecaster_steps_are_described_as_forecasts_in_the_composer():
    from off_key_core.models.pipeline_catalog import pipeline_components

    components = {item.id: item for item in pipeline_components()}
    for model_type in (
        "aberrant_holt_winters_forecaster",
        "aberrant_seasonal_naive_forecaster",
    ):
        component = components[f"detector:{model_type}"]
        assert (component.kind, component.learning) == ("detector", "online")
        assert component.output_type == "forecasts"
        assert component.group == "forecaster"
        assert "Forecast" in component.description
        assert {field.name for field in component.fields} >= {"lead", "score"}
