"""RADAR policy and generated Aberrant metadata, without importing its runtime."""

import json
from copy import deepcopy
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ADAPTIVE_MODEL_FAMILY = "adaptive_aberrant"
ADAPTIVE_MONITORING_STRATEGY = "adaptive_stream"

# Keep deployed API identifiers stable; construction uses the catalog identifiers.
MODEL_IDS = {
    "aberrant_mondrian_forest": "mondrian_isolation_forest",
    "aberrant_gadget_svm": "graph_gated_one_class_svm",
    **{
        f"aberrant_{name}": name
        for name in (
            "asd_isolation_forest",
            "half_space_trees",
            "online_isolation_forest",
            "random_cut_forest",
            "stream_random_histogram_forest",
            "x_stream",
            "knn",
            "local_outlier_factor",
            "incremental_one_class_svm_adaptive_kernel",
            "moving_average",
            "moving_average_absolute_deviation",
            "moving_geometric_average",
            "moving_harmonic_average",
            "moving_interquartile_range",
            "moving_kurtosis",
            "moving_median",
            "moving_quantile",
            "moving_skewness",
            "moving_variance",
            "moving_correlation_coefficient",
            "moving_covariance",
            "moving_mahalanobis_distance",
            "rolling_matrix_profile",
            "multivariate_rolling_matrix_profile",
        )
    },
}

# Application presets deliberately preserve the previous monitoring defaults.
MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    **{
        name: {"window_size": 100}
        for name in MODEL_IDS.values()
        if name.startswith("moving_")
    },
    "random_cut_forest": {"normalize_score": True},
    "stream_random_histogram_forest": {"max_depth": 10},
    "knn": {
        "k": 5,
        "similarity_engine": {
            "id": "faiss",
            "params": {"window_size": 1000, "warm_up": 20},
        },
    },
    "rolling_matrix_profile": {"subsequence_length": 32, "window_size": 512},
    "multivariate_rolling_matrix_profile": {
        "subsequence_length": 32,
        "window_size": 512,
    },
}

# Resource and application limits augment, rather than replace, constructor schemas.
PARAMETER_LIMITS = {
    "n_estimators": {"minimum": 1, "maximum": 2000},
    "n_trees": {"minimum": 1, "maximum": 2000},
    "num_trees": {"minimum": 1, "maximum": 2000},
    "window_size": {"minimum": 1, "maximum": 1_000_000},
    "max_samples": {"minimum": 2, "maximum": 1_000_000},
    "max_leaf_samples": {"minimum": 1, "maximum": 1_000_000},
    "subspace_size": {"minimum": 1, "maximum": 1_000_000},
    "height": {"minimum": 1, "maximum": 20},
    "max_depth": {"minimum": 2, "maximum": 128},
    "branching_factor": {"minimum": 2, "maximum": 64},
    "n_jobs": {"minimum": 1, "maximum": 64},
    "sample_size": {"minimum": 2, "maximum": 1_000_000},
    "shingle_size": {"minimum": 1, "maximum": 10_000},
    "warmup_samples": {"minimum": 1, "maximum": 1_000_000},
    "warm_up": {"minimum": 1, "maximum": 1_000_000},
    "k": {"minimum": 1, "maximum": 10_000},
    "n_chains": {"minimum": 1, "maximum": 2000},
    "depth": {"minimum": 1, "maximum": 128},
    "cms_width": {"minimum": 2, "maximum": 1_000_000},
    "cms_num_hashes": {"minimum": 1, "maximum": 128},
    "init_sample_size": {"minimum": 2, "maximum": 1_000_000},
    "max_feature_cache_size": {"minimum": 1, "maximum": 1_000_000},
    "buffer_size": {"minimum": 2, "maximum": 1_000_000},
    "sv_budget": {"minimum": 1, "maximum": 1_000_000},
    "subsequence_length": {"minimum": 2, "maximum": 10_000},
    "exclusion_zone": {"minimum": 0, "maximum": 1_000_000},
    "retrain_interval": {"minimum": 1, "maximum": 1_000_000},
    "lambda_": {"exclusiveMinimum": 0},
    "subsample": {"exclusiveMinimum": 0, "maximum": 1},
    "score_scale": {"exclusiveMinimum": 0},
    "density": {"exclusiveMinimum": 0, "maximum": 1},
    "learning_rate": {"exclusiveMinimum": 0},
    "nu": {"exclusiveMinimum": 0, "exclusiveMaximum": 1},
    "lambda_reg": {"minimum": 0},
    "initial_gamma": {"exclusiveMinimum": 0},
    "adaptation_rate": {"exclusiveMinimum": 0, "maximum": 1},
    "tolerance": {"exclusiveMinimum": 0},
    "quantile": {"minimum": 0, "maximum": 1},
}

CATALOG = json.loads(files(__package__).joinpath("adaptive_catalog.json").read_text())
ABERRANT_VERSION: str = CATALOG["aberrant_version"]
ADAPTIVE_MODELS_BY_TYPE: dict[str, dict[str, Any]] = CATALOG["models"]
BUILTIN_ADAPTIVE_MODEL_TYPES = frozenset(ADAPTIVE_MODELS_BY_TYPE)


def validate_adaptive_model_params(
    model_type: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate request shape and budgets; RADAR validates constructor semantics."""
    try:
        definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    except KeyError as exc:
        raise ValueError(f"Unknown adaptive model type: '{model_type}'") from exc
    # JSON normalization also rejects non-finite values anywhere in nested parameters.
    provided = json.loads(json.dumps(params or {}, allow_nan=False))
    _migrate_legacy_params(model_type, provided)
    merged = {**deepcopy(definition["default_parameters"]), **provided}
    try:
        Draft202012Validator(definition["parameter_schema"]).validate(merged)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.path)
        raise ValueError(
            f"Invalid parameters for '{model_type}': {path}: {exc.message}"
        ) from exc
    if model_type == "aberrant_knn":
        engine_params = merged["similarity_engine"]["params"]
        if not merged["k"] <= engine_params["warm_up"] <= engine_params["window_size"]:
            raise ValueError("KNN requires k <= warm_up <= window_size")
    if (
        model_type == "aberrant_local_outlier_factor"
        and merged["k"] > merged["window_size"]
    ):
        raise ValueError("LocalOutlierFactor requires k <= window_size")
    if (
        model_type == "aberrant_half_space_trees"
        and merged["n_trees"] * (2 ** (merged["height"] + 1) - 1) > 2_000_000
    ):
        raise ValueError("Half-Space Trees exceeds the 2,000,000-node resource budget")
    return merged


def _migrate_legacy_params(model_type: str, provided: dict[str, Any]) -> None:
    """Translate the persisted 0.5 API shape without hiding conflicting values."""
    aliases = {
        "aberrant_stream_random_histogram_forest": ("max_bins", "max_depth"),
        "aberrant_moving_geometric_average": ("absolute_values", "absoluteValues"),
    }
    if model_type in aliases:
        previous, current = aliases[model_type]
        if previous in provided:
            if current in provided and provided[current] != provided[previous]:
                raise ValueError(f"Conflicting {previous} and {current} values")
            provided[current] = provided.pop(previous)
    if model_type == "aberrant_knn":
        legacy = {
            key: provided.pop(key)
            for key in ("window_size", "warm_up")
            if key in provided
        }
        if legacy:
            if "similarity_engine" in provided:
                raise ValueError(
                    "Do not mix legacy KNN parameters with similarity_engine"
                )
            engine = deepcopy(
                ADAPTIVE_MODELS_BY_TYPE[model_type]["default_parameters"][
                    "similarity_engine"
                ]
            )
            engine["params"].update(legacy)
            provided["similarity_engine"] = engine


def adaptive_model_metadata(model_type: str) -> dict[str, Any]:
    """Provider metadata for API responses, independent of database schema versions."""
    definition = ADAPTIVE_MODELS_BY_TYPE.get(model_type)
    if definition is None:
        return {}
    return {
        key: deepcopy(definition[key])
        for key in (
            "catalog_id",
            "algorithm_family",
            "available",
            "default_capabilities",
        )
    }
