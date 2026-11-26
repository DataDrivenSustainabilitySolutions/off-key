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

# A detector's model type is its catalog identifier with an ``aberrant_`` prefix.
MODEL_IDS = {
    f"aberrant_{name}": name
    for name in (
        "mondrian_isolation_forest",
        "asd_isolation_forest",
        "half_space_trees",
        "online_isolation_forest",
        "random_cut_forest",
        "rhf",
        "xstream",
        "knn",
        "local_outlier_factor",
        "adaptive_one_class_svm",
        "moving_zscore",
        "moving_mad",
        "moving_correlation_coefficient",
        "moving_covariance",
        "moving_mahalanobis_distance",
        "rolling_matrix_profile",
        "multivariate_rolling_matrix_profile",
        "damp",
        "online_ecod",
        "online_copod",
        "loda",
    )
}

# A forecaster step scores one feature against the forecast made for it: each is
# Aberrant's residual detector around one forecaster. The step's settings are the
# forecaster's own, plus how far ahead it forecasts and how the miss is scored.
RESIDUAL_DETECTOR = "residual_detector"
FORECASTER_IDS = {
    "aberrant_seasonal_naive_forecaster": "seasonal_naive",
    "aberrant_holt_winters_forecaster": "holt_winters",
    "aberrant_autoregressive_forecaster": "autoregressive",
    "aberrant_kalman_forecaster": "kalman_forecaster",
    "aberrant_echo_state_forecaster": "echo_state_forecaster",
    "aberrant_lag_forecaster": "lag_forecaster",
    "aberrant_ensemble_forecaster": "ensemble_forecaster",
}
# The components a forecaster holds: a lag forecaster's regressor and an
# ensemble's members. A design names each by its ``id`` beside its own settings,
# and every member forecasts as far ahead as the step does. Members hold no
# components of their own, which keeps each step's settings one level deep.
REGRESSOR_IDS = (
    "random_fourier_regressor",
    "rls_regressor",
    "knn_regressor",
    "hoeffding_tree_regressor",
    "adaptive_random_forest_regressor",
)
MEMBER_IDS = (
    "autoregressive",
    "kalman_forecaster",
    "holt_winters",
    "seasonal_naive",
    "echo_state_forecaster",
)
COMPONENT_SETTINGS = {"regressor": REGRESSOR_IDS, "forecasters": MEMBER_IDS}
# A regressor predicts the present, and an ensemble's horizon is its members'.
_NO_HORIZON = frozenset((*REGRESSOR_IDS, "ensemble_forecaster"))
# A lag forecaster starts from the regressor that forecast best in Aberrant's
# benchmark, and an ensemble from two linear members and a nonlinear one.
COMPONENT_DEFAULTS: dict[str, dict[str, Any]] = {
    "lag_forecaster": {"regressor": {"id": "random_fourier_regressor"}},
    "ensemble_forecaster": {
        "forecasters": [
            {"id": "autoregressive"},
            {"id": "kalman_forecaster"},
            {"id": "echo_state_forecaster"},
        ]
    },
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
    "rhf": {"max_depth": 10},
    "knn": {"k": 5},
    "rolling_matrix_profile": {"subsequence_length": 32, "window_size": 512},
    "damp": {"subsequence_length": 32},
    "multivariate_rolling_matrix_profile": {
        "subsequence_length": 32,
        "window_size": 512,
    },
}

# Settings RADAR never passes: it times each observation itself, and KNN
# searches its window with NumPy.
UNSUPPORTED_PARAMETERS = ("time_key", "backend")

# Resource and application limits augment, rather than replace, constructor schemas.
PARAMETER_LIMITS = {
    "n_trees": {"minimum": 1, "maximum": 2000},
    "window_size": {"minimum": 1, "maximum": 1_000_000},
    "max_samples": {"minimum": 2, "maximum": 1_000_000},
    "max_leaf_samples": {"minimum": 1, "maximum": 1_000_000},
    "subspace_size": {"minimum": 1, "maximum": 1_000_000},
    "height": {"minimum": 1, "maximum": 20},
    "max_depth": {"minimum": 2, "maximum": 128},
    "branching_factor": {"minimum": 2, "maximum": 64},
    "sample_size": {"minimum": 2, "maximum": 1_000_000},
    "shingle_size": {"minimum": 1, "maximum": 10_000},
    "warm_up": {"minimum": 1, "maximum": 1_000_000},
    "k": {"minimum": 1, "maximum": 10_000},
    "n_chains": {"minimum": 1, "maximum": 2000},
    "depth": {"minimum": 1, "maximum": 128},
    "sketch_width": {"minimum": 2, "maximum": 1_000_000},
    "n_hashes": {"minimum": 1, "maximum": 128},
    "max_feature_cache_size": {"minimum": 1, "maximum": 1_000_000},
    "buffer_size": {"minimum": 2, "maximum": 1_000_000},
    "sv_budget": {"minimum": 1, "maximum": 1_000_000},
    "subsequence_length": {"minimum": 2, "maximum": 10_000},
    "exclusion_zone": {"minimum": 0, "maximum": 1_000_000},
    "retrain_interval": {"minimum": 1, "maximum": 1_000_000},
    "lifetime": {"exclusiveMinimum": 0},
    "subsample": {"exclusiveMinimum": 0, "maximum": 1},
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
    "order": {"minimum": 0, "maximum": 64},
    "seasonal_order": {"minimum": 0, "maximum": 8},
    "difference": {"minimum": 0, "maximum": 2},
    "seasonal_difference": {"minimum": 0, "maximum": 1},
    "forgetting": {"exclusiveMinimum": 0, "maximum": 1},
    "delta": {"exclusiveMinimum": 0},
    "level_ratio": {"minimum": 0},
    "slope_ratio": {"minimum": 0},
    "season_ratio": {"minimum": 0},
    "harmonics": {"minimum": 0, "maximum": 250},
    "ratio_rate": {"exclusiveMinimum": 0},
    "n_reservoir": {"minimum": 1, "maximum": 1000},
    "spectral_radius": {"exclusiveMinimum": 0},
    "leak_rate": {"exclusiveMinimum": 0, "maximum": 1},
    "input_scale": {"exclusiveMinimum": 0},
    "connectivity": {"exclusiveMinimum": 0, "maximum": 1},
    "n_components": {"minimum": 1, "maximum": 4096},
    "length_scale": {"exclusiveMinimum": 0},
    "C": {"exclusiveMinimum": 0},
    "epsilon": {"minimum": 0},
    "huber": {"exclusiveMinimum": 0},
    "l2": {"minimum": 0},
    "grace_period": {"minimum": 1, "maximum": 1_000_000},
    "tau": {"minimum": 0},
    "n_bins": {"minimum": 2, "maximum": 1024},
    "n_models": {"minimum": 1, "maximum": 100},
    "max_features": {"minimum": 1, "maximum": 10_000},
    "lambda_value": {"exclusiveMinimum": 0},
    "drift_delta": {"exclusiveMinimum": 0, "exclusiveMaximum": 1},
    "warning_delta": {"exclusiveMinimum": 0, "exclusiveMaximum": 1},
    "forecasters": {"minItems": 2, "maxItems": 8},
}

# Limits that differ for one component. Season length 1 is no season, or for
# the seasonal naive forecaster the last value; a tree's delta is a probability.
_NO_SEASON = {"season_length": {"minimum": 1, "maximum": 500_000}}
_SPLIT_CONFIDENCE = {"delta": {"exclusiveMinimum": 0, "exclusiveMaximum": 1}}
FORECASTER_LIMITS: dict[str, dict[str, dict[str, Any]]] = {
    "seasonal_naive": _NO_SEASON,
    "autoregressive": _NO_SEASON,
    "kalman_forecaster": _NO_SEASON,
    "echo_state_forecaster": _NO_SEASON,
    "lag_forecaster": _NO_SEASON,
    "hoeffding_tree_regressor": _SPLIT_CONFIDENCE,
    "adaptive_random_forest_regressor": _SPLIT_CONFIDENCE,
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
            "requires_unit_interval": False,
            "score_kind": "non_negative",
            "state": "bounded",
            "warm_up": {"required": 32, "unit": "events"},
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
            "requires_unit_interval": False,
            "score_kind": "signed",
            "state": "stateless",
            "warm_up": {"required": 0, "unit": "events"},
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
    "aberrant_rhf": ("window_size",),
    "aberrant_asd_isolation_forest": ("window_size", "max_samples"),
    "aberrant_random_cut_forest": ("warm_up", "sample_size"),
    "aberrant_xstream": ("warm_up",),
    "aberrant_moving_zscore": ("warm_up", "window_size"),
    "aberrant_moving_mad": ("warm_up", "window_size"),
    "aberrant_online_ecod": ("warm_up",),
    "aberrant_online_copod": ("warm_up",),
    "aberrant_loda": ("warm_up",),
}


def detector_warmup(model_type: str, params: dict[str, Any]) -> int:
    """The observations a streaming detector learns before it can score, as
    Aberrant counts them for these settings; 0 where that is not known here."""
    definition = ADAPTIVE_MODELS_BY_TYPE.get(model_type)
    if definition is None:
        return 0
    warmup = definition["default_capabilities"].get("warm_up") or {}
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
        return int(warmup.get("required") or 0)
    settings = definition.get("default_parameters", {}) | {
        key: value for key, value in params.items() if value is not None
    }
    if model_type == "aberrant_damp":
        return _damp_warmup(settings)
    # Elsewhere the warm-up follows the settings in ways not mirrored here;
    # RADAR checks it when the run starts.
    return 0


def _damp_warmup(settings: Mapping[str, Any]) -> int:
    """DAMP scores from its start index on, which by default is four
    subsequences in, once a whole subsequence ends there."""
    length = settings.get("subsequence_length")
    if not isinstance(length, int) or length < 2:
        return 0
    start = settings.get("start_index")
    start = start if isinstance(start, int) and start > 0 else 4 * length
    return start + length - 2


# Detectors that score each observation on its own, as if it had no past. On a
# series that follows its past they score the level unless a step before them
# carries time: lags, a change, a rolling window or the clock.
POINT_DETECTORS = frozenset(
    {
        "mondrian_isolation_forest",
        "asd_isolation_forest",
        "half_space_trees",
        "online_isolation_forest",
        "random_cut_forest",
        "rhf",
        "xstream",
        "knn",
        "local_outlier_factor",
        "adaptive_one_class_svm",
        "online_ecod",
        "online_copod",
        "loda",
    }
)


def detector_component(model_type: str) -> str:
    """The pipeline component of a streaming detector's model type."""
    own = model_type in PRETRAINED_FORECASTERS or model_type in RULE_DETECTORS
    return model_type if own else f"detector:{model_type}"


# Detector parameters bound from the feature schema, never from user input.
BOUND_PARAMETER_NAMES = ("features", "key", "target")


def bind_detector_parameters(
    bound_parameters: Iterable[str],
    params: Mapping[str, Any],
    feature_names: list[str] | None,
) -> dict[str, Any]:
    """Fill a detector's bound parameters from the features it receives."""
    result = dict(params)
    for name in bound_parameters:
        if name in ("key", "target"):
            result[name] = feature_names[0] if feature_names else None
        else:
            result[name] = feature_names
    return result


def _component_parameters(
    component_id: str, params: Mapping[str, Any], horizon: Any
) -> dict[str, Any]:
    """A component's settings, with the components it holds as Aberrant's
    ``{"id", "params"}`` and every forecaster's horizon set."""
    result: dict[str, Any] = {}
    for name, value in params.items():
        if name == "regressor" and isinstance(value, Mapping):
            result[name] = _held_component(value, horizon)
        elif name == "forecasters" and isinstance(value, list):
            result[name] = [
                _held_component(item, horizon) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            result[name] = value
    if horizon is not None and component_id not in _NO_HORIZON:
        result["horizon"] = horizon
    return result


def _held_component(value: Mapping[str, Any], horizon: Any) -> dict[str, Any]:
    settings = {name: item for name, item in value.items() if name != "id"}
    component_id = value.get("id")
    return {
        "id": component_id,
        "params": _component_parameters(str(component_id), settings, horizon),
    }


def forecaster_parameters(forecaster_id: str, params: Mapping[str, Any]) -> dict:
    """A forecaster step's settings as Aberrant's residual detector parameters.

    The forecaster, and every member of an ensemble, forecasts exactly as far
    ahead as the lead that is scored.
    """
    outer = {name: params[name] for name in _RESIDUAL_SETTINGS if name in params}
    inner = {name: value for name, value in params.items() if name not in outer}
    model = _component_parameters(forecaster_id, inner, outer.get("lead"))
    return {**outer, "model": {"id": forecaster_id, "params": model}}


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
    merged = {**deepcopy(definition["default_parameters"]), **provided}
    validate_parameter_schema(
        f"Invalid parameters for '{model_type}'", definition["parameter_schema"], merged
    )
    if (
        model_type in ("aberrant_knn", "aberrant_local_outlier_factor")
        and merged["k"] > merged["window_size"]
    ):
        name = "KNN" if model_type == "aberrant_knn" else "LocalOutlierFactor"
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("k",),
                    message=f"{name} requires k <= window_size",
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
        model_type == "aberrant_holt_winters_forecaster"
        and merged["gamma"] > 1 - merged["alpha"]
    ):
        raise parameter_error(
            model_type,
            [
                ParameterIssue(
                    code="invalid_value",
                    loc=("gamma",),
                    message="Holt-Winters forecaster requires gamma <= 1 - alpha",
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
