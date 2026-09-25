"""Catalog provenance, API metadata, and legacy configuration migration."""

import json
import subprocess
import sys

import pytest
from aberrant import __version__
from aberrant.catalog import DetectorConfig
from off_key_api_gateway.api.v1.monitors import _normalize_models_for_gateway
from off_key_core.models import (
    ABERRANT_VERSION,
    ADAPTIVE_MODELS_BY_TYPE,
    adaptive_model_metadata,
    validate_adaptive_model_params,
)
from off_key_core.models.adaptive import CATALOG
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.catalog import generate_catalog
from off_key_tactic_middleware.api.v1.models import ModelInfo


def test_generated_catalog_matches_pinned_runtime():
    assert ABERRANT_VERSION == __version__ == "1.1.0"
    assert generate_catalog() == CATALOG


def test_shared_configuration_does_not_import_numerical_runtimes():
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from off_key_core.schemas.radar import AdaptiveStreamConfig; "
            "AdaptiveStreamConfig(); "
            "assert not {'aberrant', 'numpy', 'scipy', 'faiss'} & sys.modules.keys()",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


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


def test_catalog_capabilities_survive_tactic_and_gateway_responses():
    model_type = "aberrant_rolling_matrix_profile"
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    response = ModelInfo(
        model_type=model_type,
        family="adaptive_aberrant",
        name=definition["name"],
        import_paths=[definition["import_path"]],
        parameter_schema=definition["parameter_schema"],
        default_parameters=definition["default_parameters"],
        strategy="adaptive_stream",
        version=ABERRANT_VERSION,
        requires_special_handling=False,
        **adaptive_model_metadata(model_type),
    )
    payload = _normalize_models_for_gateway([response.model_dump()])[model_type]
    assert payload["family"] == "adaptive_aberrant"
    assert payload["algorithm_family"] == "time_series"
    assert payload["catalog_id"] == "rolling_matrix_profile"
    assert payload["default_capabilities"]["feature_count"] == {
        "minimum": 1,
        "maximum": 1,
    }
    assert payload["available"] is True
    json.dumps(payload, allow_nan=False)
