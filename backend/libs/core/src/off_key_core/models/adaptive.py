"""RADAR policy and generated Aberrant metadata, without importing its runtime."""

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from importlib.resources import files
from typing import Any

from ..schemas.pipeline_versions import RULE_DETECTOR
from .parameter_validation import (
    ParameterIssue,
    parameter_error,
    validate_parameter_schema,
)

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
            "seasonal_residual_detector",
        )
    },
}

# A forecaster step scores one feature against the forecast made for it: each is
# Aberrant's residual detector around one forecaster. The step's settings are the
# forecaster's own, plus how far ahead it forecasts and how the miss is scored.
RESIDUAL_DETECTOR = "residual_detector"
FORECASTER_IDS = {
    "aberrant_seasonal_naive_forecaster": "seasonal_naive",
    "aberrant_holt_winters_forecaster": "holt_winters",
}
# Settings of the residual detector itself; the others belong to its forecaster.
_RESIDUAL_SETTINGS = ("target", "lead", "score")

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
    # Two seasons are learned before scoring, and they must fit the training window.
    "season_length": {"minimum": 2, "maximum": 500_000},
    "alpha": {"minimum": 0, "maximum": 1},
    "beta": {"minimum": 0, "maximum": 1},
    "gamma": {"minimum": 0, "maximum": 1},
    "residual_alpha": {"exclusiveMinimum": 0, "maximum": 1},
    "min_scale": {"exclusiveMinimum": 0},
    # A forecast is compared with the value that arrives this many updates later.
    "lead": {"minimum": 1, "maximum": 1024},
}

# Limits that differ for one forecaster. Season length 1 repeats the last value.
FORECASTER_LIMITS: dict[str, dict[str, dict[str, Any]]] = {
    "seasonal_naive": {"season_length": {"minimum": 1, "maximum": 500_000}},
}

# A pretrained forecaster's weights live in the shared forecast service, so it is
# not an Aberrant component and not in the generated catalog. RADAR wraps the
# service in Aberrant's residual detector; its key is its component identifier.
TIMESTRAL = "forecast.timestral"
# The checkpoints the forecast service offers, smallest first.
TIMESTRAL_CHECKPOINTS = (
    "mistralai/Timestral-5M",
    "mistralai/Timestral-28M",
    "mistralai/Timestral-123M",
    "mistralai/Timestral-209M",
)
PRETRAINED_FORECASTERS: dict[str, dict[str, Any]] = {
    TIMESTRAL: {
        "catalog_id": RESIDUAL_DETECTOR,
        "forecaster_id": TIMESTRAL,
        "name": "Timestral forecaster",
        "import_path": "off_key_mqtt_radar.forecasting.ServiceForecaster",
        "algorithm_family": "forecast",
        "available": True,
        "parameter_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "checkpoint": {
                    "enum": list(TIMESTRAL_CHECKPOINTS),
                    "default": TIMESTRAL_CHECKPOINTS[0],
                },
                # How many recent values the model reads for each forecast.
                "context_length": {
                    "type": "integer",
                    "default": 512,
                    "minimum": 16,
                    "maximum": 32_768,
                },
                # Forecasts start once this many values have arrived.
                "minimum_context": {
                    "type": "integer",
                    "default": 32,
                    "minimum": 16,
                    "maximum": 32_768,
                },
                "lead": {**PARAMETER_LIMITS["lead"], "type": "integer", "default": 1},
                "score": {"enum": ["absolute", "scaled"], "default": "scaled"},
                "min_scale": {
                    **PARAMETER_LIMITS["min_scale"],
                    "type": "number",
                    "default": 1e-06,
                },
            },
        },
        "default_parameters": {
            "checkpoint": TIMESTRAL_CHECKPOINTS[0],
            "context_length": 512,
            "minimum_context": 32,
            "lead": 1,
            "score": "scaled",
            "min_scale": 1e-06,
        },
        "default_capabilities": {
            "event_kind": "univariate",
            "feature_count": {"minimum": 1, "maximum": 1},
            "feature_schema": "fixed",
            "higher_is_more_anomalous": True,
            "requires_unit_interval": False,
            "resettable": False,
            "score_kind": "non_negative",
            "state": "bounded",
            "warmup": {"minimum": 32, "unit": "events"},
        },
        "bound_parameters": ["target"],
    }
}

# A rule detector is RADAR's own as well. It has no settings: a step before it
# computes the feature whose value is the score, such as a flag that is 1 where
# a limit is crossed, or how far a reading is from what it should be.
RULE_DETECTORS: dict[str, dict[str, Any]] = {
    RULE_DETECTOR: {
        "catalog_id": RULE_DETECTOR,
        "name": "Rule detector",
        "description": "Takes one feature's value as the score, with no training.",
        "import_path": "off_key_mqtt_radar.rules.FeatureScore",
        "algorithm_family": "rule",
        "available": True,
        "parameter_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        "default_parameters": {},
        "default_capabilities": {
            "event_kind": "univariate",
            "feature_count": {"minimum": 1, "maximum": 1},
            "feature_schema": "fixed",
            "higher_is_more_anomalous": True,
            "requires_unit_interval": False,
            "resettable": True,
            "score_kind": "signed",
            "state": "stateless",
            "warmup": {"minimum": 0, "unit": "events"},
        },
        "bound_parameters": ["key"],
    }
}

CATALOG = json.loads(files(__package__).joinpath("adaptive_catalog.json").read_text())
ABERRANT_VERSION: str = CATALOG["aberrant_version"]
ADAPTIVE_MODELS_BY_TYPE: dict[str, dict[str, Any]] = {
    **CATALOG["models"],
    **PRETRAINED_FORECASTERS,
    **RULE_DETECTORS,
}


# The settings a detector's warm-up follows, where Aberrant ties it to one:
# the first set of them names the observations it keeps before it scores.
_WARMUP_SETTINGS: dict[str, tuple[str, ...]] = {
    "aberrant_half_space_trees": ("window_size",),
    "aberrant_stream_random_histogram_forest": ("window_size",),
    "aberrant_asd_isolation_forest": ("window_size", "max_samples"),
    "aberrant_random_cut_forest": ("warmup_samples", "sample_size"),
    "aberrant_x_stream": ("init_sample_size", "window_size"),
}
# A seasonal model has seen a cycle twice before it scores.
_WARMUP_SEASONS = {"aberrant_seasonal_residual_detector": 2}


def detector_warmup(model_type: str, params: dict[str, Any]) -> int:
    """The observations a streaming detector learns before it can score, as
    Aberrant counts them for these settings; 0 where that is not known here."""
    definition = ADAPTIVE_MODELS_BY_TYPE.get(model_type)
    if definition is None:
        return 0
    warmup = definition["default_capabilities"].get("warmup") or {}
    if warmup.get("unit") != "events":
        return 0
    names = _WARMUP_SETTINGS.get(model_type)
    if names:
        defaults = definition.get("default_parameters", {})
        # A setting given wins over a default of an earlier one.
        for source in (params, defaults):
            for name in names:
                value = source.get(name)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
        return int(warmup.get("minimum") or 0)
    settings = definition.get("default_parameters", {}) | {
        key: value for key, value in params.items() if value is not None
    }
    seasons = _WARMUP_SEASONS.get(model_type)
    season = settings.get("season_length")
    if seasons and isinstance(season, int) and season > 0:
        return seasons * season
    # Elsewhere the warm-up follows the settings in ways not mirrored here;
    # RADAR checks it when the run starts.
    return 0


def detector_component(model_type: str) -> str:
    """The pipeline component of a streaming detector's model type."""
    own = model_type in PRETRAINED_FORECASTERS or model_type in RULE_DETECTORS
    return model_type if own else f"detector:{model_type}"


# Detector parameters bound from the feature schema, never from user input.
BOUND_PARAMETER_NAMES = ("abs_diff", "key", "keys", "target")


def bind_detector_parameters(
    bound_parameters: Iterable[str],
    params: Mapping[str, Any],
    feature_names: list[str] | None,
) -> dict[str, Any]:
    """Fill a detector's bound parameters from the features it receives."""
    result = dict(params)
    for name in bound_parameters:
        if name == "abs_diff":
            result[name] = True
        elif name in ("key", "target"):
            result[name] = feature_names[0] if feature_names else None
        else:
            result[name] = feature_names
    return result


def forecaster_parameters(forecaster_id: str, params: Mapping[str, Any]) -> dict:
    """A forecaster step's settings as Aberrant's residual detector parameters.

    The forecaster forecasts exactly as far ahead as the lead that is scored.
    """
    outer = {name: params[name] for name in _RESIDUAL_SETTINGS if name in params}
    inner = {name: value for name, value in params.items() if name not in outer}
    if outer.get("lead") is not None:
        inner["horizon"] = outer["lead"]
    return {**outer, "model": {"id": forecaster_id, "params": inner}}


def aberrant_model(definition: Mapping[str, Any], params: Mapping[str, Any]) -> dict:
    """The Aberrant model configuration for a detector's bound parameters."""
    forecaster_id = definition.get("forecaster_id")
    return {
        "id": definition["catalog_id"],
        "params": forecaster_parameters(forecaster_id, params)
        if forecaster_id
        else dict(params),
    }


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
    validate_parameter_schema(
        f"Invalid parameters for '{model_type}'", definition["parameter_schema"], merged
    )
    if model_type == "aberrant_knn":
        engine_params = merged["similarity_engine"]["params"]
        if not merged["k"] <= engine_params["warm_up"] <= engine_params["window_size"]:
            raise parameter_error(
                model_type,
                [
                    ParameterIssue(
                        code="invalid_value",
                        loc=("similarity_engine", "params", "warm_up"),
                        message="KNN requires k <= warm_up <= window_size",
                    )
                ],
            )
    if (
        model_type == "aberrant_local_outlier_factor"
        and merged["k"] > merged["window_size"]
    ):
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("k",),
                    message="LocalOutlierFactor requires k <= window_size",
                )
            ],
        )
    if (
        model_type == "aberrant_half_space_trees"
        and merged["n_trees"] * (2 ** (merged["height"] + 1) - 1) > 2_000_000
    ):
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("height",),
                    message=(
                        "Half-Space Trees exceeds the 2,000,000-node resource budget"
                    ),
                )
            ],
        )
    if (
        model_type
        in ("aberrant_seasonal_residual_detector", "aberrant_holt_winters_forecaster")
        and merged["gamma"] > 1 - merged["alpha"]
    ):
        name = (
            "Seasonal residual detector"
            if model_type == "aberrant_seasonal_residual_detector"
            else "Holt-Winters forecaster"
        )
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("gamma",),
                    message=f"{name} requires gamma <= 1 - alpha",
                )
            ],
        )
    if model_type in PRETRAINED_FORECASTERS and (
        merged["minimum_context"] > merged["context_length"]
    ):
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("minimum_context",),
                    message="minimum_context must not exceed context_length",
                )
            ],
        )
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
