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
from off_key_core.models.adaptive import (
    CATALOG,
    FORECASTER_IDS,
    aberrant_model,
    bind_detector_parameters,
)
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.catalog import generate_catalog

from tests.support.pipelines import template


def detector_mapping(config: AdaptiveStreamConfig, features: list[str]) -> dict:
    """The Aberrant mapping a detector's settings bind to for these features."""
    definition = ADAPTIVE_MODELS_BY_TYPE[config.model_type]
    params = bind_detector_parameters(
        definition["bound_parameters"], config.model_params, features
    )
    return {"version": 2, "model": aberrant_model(definition, params)}


def test_generated_catalog_matches_pinned_runtime():
    assert ABERRANT_VERSION == __version__ == "2.0.0"
    assert generate_catalog() == CATALOG


@pytest.mark.parametrize(
    ("model_type", "params"),
    [
        ("aberrant_rhf", {"max_bins": 8}),
        ("aberrant_knn", {"window_size": 20, "warm_up": 5}),
        ("aberrant_knn", {"window_size": 20, "backend": "faiss"}),
        ("aberrant_knn", {"k": 30, "window_size": 20}),
        ("aberrant_knn", {"window_size": 2_000_000}),
        ("aberrant_moving_zscore", {"abs_diff": False}),
        ("aberrant_moving_zscore", {"key": "unsubscribed_sensor"}),
        ("aberrant_online_isolation_forest", {"n_trees": 2001}),
        ("aberrant_online_isolation_forest", {"n_trees": True}),
        ("aberrant_online_isolation_forest", {"subsample": float("nan")}),
        ("aberrant_half_space_trees", {"n_trees": 2000, "height": 20}),
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
        ("aberrant_autoregressive_forecaster", {"difference": 3}),
        ("aberrant_autoregressive_forecaster", {"order": 65}),
        ("aberrant_echo_state_forecaster", {"n_reservoir": 5000}),
        ("aberrant_echo_state_forecaster", {"leak_rate": 1.5}),
        ("aberrant_kalman_forecaster", {"level_ratio": -1.0}),
        ("aberrant_lag_forecaster", {"regressor": {"id": "sgd_regressor"}}),
        ("aberrant_lag_forecaster", {"regressor": {"id": "knn_regressor", "k": 0}}),
        (
            "aberrant_lag_forecaster",
            {"regressor": {"id": "hoeffding_tree_regressor", "delta": 1.0}},
        ),
        ("aberrant_lag_forecaster", {"regressor": {"grace_period": 10}}),
        ("aberrant_ensemble_forecaster", {"forecasters": [{"id": "autoregressive"}]}),
        (
            "aberrant_ensemble_forecaster",
            {"forecasters": [{"id": "autoregressive"}, {"id": "lag_forecaster"}]},
        ),
        (
            "aberrant_ensemble_forecaster",
            {
                "forecasters": [
                    {"id": "autoregressive", "horizon": 3},
                    {"id": "kalman_forecaster"},
                ]
            },
        ),
        (
            "aberrant_ensemble_forecaster",
            {"forecasters": [{"id": "holt_winters"}, {"id": "kalman_forecaster"}]},
        ),
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


def test_seasonal_forecast_detector_in_a_design_checks_its_season_and_features():
    data = template("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    detector["component"] = "detector:aberrant_holt_winters_forecaster"
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
        (
            "aberrant_autoregressive_forecaster",
            "autoregressive",
            {"order": 3, "lead": 2},
            {"order": 3, "horizon": 2},
            10,
        ),
        (
            "aberrant_kalman_forecaster",
            "kalman_forecaster",
            {"season_length": 24},
            {"season_length": 24, "horizon": 1, "learn_ratios": True},
            25,
        ),
        (
            "aberrant_echo_state_forecaster",
            "echo_state_forecaster",
            {},
            {"n_reservoir": 100, "horizon": 1},
            33,
        ),
        (
            "aberrant_lag_forecaster",
            "lag_forecaster",
            {"regressor": {"id": "hoeffding_tree_regressor", "grace_period": 50}},
            {
                "order": 3,
                "horizon": 1,
                "regressor": {
                    "id": "hoeffding_tree_regressor",
                    "params": {"grace_period": 50},
                },
            },
            37,
        ),
        (
            "aberrant_ensemble_forecaster",
            "ensemble_forecaster",
            {"lead": 2},
            {
                "forecasters": [
                    {"id": "autoregressive", "params": {"horizon": 2}},
                    {"id": "kalman_forecaster", "params": {"horizon": 2}},
                    {"id": "echo_state_forecaster", "params": {"horizon": 2}},
                ]
            },
            37,
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
    model = detector_mapping(config, ["x"])["model"]
    assert model["id"] == "residual_detector"
    assert model["params"]["target"] == "x"
    assert model["params"]["lead"] == params["lead"]
    assert model["params"]["model"]["id"] == forecaster_id
    assert forecaster_params.items() <= model["params"]["model"]["params"].items()
    capabilities = DetectorConfig.from_mapping(
        detector_mapping(config, ["x"])
    ).capabilities()
    assert capabilities.warmup == warmup


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
    for model_type in FORECASTER_IDS:
        component = components[f"detector:{model_type}"]
        assert (component.kind, component.learning) == ("detector", "online")
        assert component.output_type == "forecasts"
        assert component.group == "forecaster"
        assert "Forecast" in component.description
        assert {field.name for field in component.fields} >= {"lead", "score"}
