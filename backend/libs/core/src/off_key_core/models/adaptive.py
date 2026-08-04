"""Immutable catalog and parameter contracts for the aberrant adaptive lane."""

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ADAPTIVE_MODEL_FAMILY = "adaptive_aberrant"
ADAPTIVE_MONITORING_STRATEGY = "adaptive_stream"
ABERRANT_VERSION = "0.5.0"


class AdaptiveHyperparameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ASDIsolationForestParams(AdaptiveHyperparameters):
    n_estimators: int = Field(100, ge=1, le=2_000)
    max_samples: int = Field(256, ge=2, le=1_000_000)
    seed: int | None = None


class HalfSpaceTreesParams(AdaptiveHyperparameters):
    n_trees: int = Field(10, ge=1, le=2_000)
    height: int = Field(8, ge=1, le=64)
    window_size: int = Field(250, ge=2, le=1_000_000)
    seed: int | None = None


class MondrianForestParams(AdaptiveHyperparameters):
    n_estimators: int = Field(100, ge=1, le=2_000)
    subspace_size: int = Field(256, ge=1, le=1_000_000)
    lambda_: float = Field(1.0, gt=0, allow_inf_nan=False)
    seed: int | None = None


class OnlineIsolationForestParams(AdaptiveHyperparameters):
    num_trees: int = Field(100, ge=1, le=2_000)
    max_leaf_samples: int = Field(32, ge=1, le=1_000_000)
    tree_type: Literal["adaptive", "fixed"] = "adaptive"
    subsample: float = Field(1.0, gt=0, le=1, allow_inf_nan=False)
    window_size: int = Field(2048, ge=2, le=1_000_000)
    branching_factor: int = Field(2, ge=2, le=64)
    metric: Literal["axisparallel", "hyperplane"] = "axisparallel"
    n_jobs: int = Field(1, ge=1, le=64)


class RandomCutForestParams(AdaptiveHyperparameters):
    n_trees: int = Field(40, ge=1, le=2_000)
    sample_size: int = Field(256, ge=2, le=1_000_000)
    shingle_size: int = Field(1, ge=1, le=10_000)
    warmup_samples: int | None = Field(None, ge=1, le=1_000_000)
    normalize_score: bool = True
    score_scale: float = Field(8.0, gt=0, allow_inf_nan=False)
    seed: int | None = None


class StreamRandomHistogramForestParams(AdaptiveHyperparameters):
    n_estimators: int = Field(25, ge=1, le=2_000)
    max_bins: int = Field(10, ge=2, le=10_000)
    window_size: int = Field(256, ge=2, le=1_000_000)
    seed: int | None = None


class XStreamParams(AdaptiveHyperparameters):
    k: int = Field(100, ge=1, le=10_000)
    n_chains: int = Field(100, ge=1, le=2_000)
    depth: int = Field(15, ge=1, le=128)
    cms_width: int = Field(1024, ge=2, le=1_000_000)
    cms_num_hashes: int = Field(4, ge=1, le=128)
    window_size: int = Field(256, ge=2, le=1_000_000)
    init_sample_size: int = Field(256, ge=2, le=1_000_000)
    density: float = Field(1 / 3, gt=0, le=1, allow_inf_nan=False)
    max_feature_cache_size: int | None = Field(10_000, ge=1)
    seed: int | None = None


class KNNParams(AdaptiveHyperparameters):
    k: int = Field(5, ge=1, le=10_000)
    window_size: int = Field(1000, ge=1, le=1_000_000)
    warm_up: int = Field(20, ge=1, le=1_000_000)


class LocalOutlierFactorParams(AdaptiveHyperparameters):
    k: int = Field(10, ge=1, le=10_000)
    window_size: int = Field(1000, ge=2, le=1_000_000)
    distance: Literal["euclidean", "manhattan"] = "euclidean"


class GADGETSVMParams(AdaptiveHyperparameters):
    graph: dict[int, list[int]] | None = None
    threshold: float = Field(0.0, allow_inf_nan=False)
    learning_rate: float = Field(0.01, gt=0, allow_inf_nan=False)
    nu: float = Field(0.5, gt=0, lt=1, allow_inf_nan=False)
    lambda_reg: float = Field(0.01, ge=0, allow_inf_nan=False)


class AdaptiveKernelSVMParams(AdaptiveHyperparameters):
    nu: float = Field(0.1, gt=0, lt=1, allow_inf_nan=False)
    initial_gamma: float = Field(1.0, gt=0, allow_inf_nan=False)
    gamma_bounds: tuple[float, float] = (0.001, 100.0)
    adaptation_rate: float = Field(0.1, gt=0, le=1, allow_inf_nan=False)
    buffer_size: int = Field(200, ge=2, le=1_000_000)
    sv_budget: int = Field(100, ge=1, le=1_000_000)
    tolerance: float = Field(1e-6, gt=0, allow_inf_nan=False)
    seed: int | None = None


class MovingUnivariateParams(AdaptiveHyperparameters):
    window_size: int = Field(100, ge=1, le=1_000_000)


class MovingGeometricAverageParams(MovingUnivariateParams):
    absolute_values: bool = False


class MovingQuantileParams(MovingUnivariateParams):
    quantile: float = Field(0.5, ge=0, le=1, allow_inf_nan=False)


class MovingBivariateParams(AdaptiveHyperparameters):
    window_size: int = Field(100, ge=2, le=1_000_000)
    bias: bool = True


class MovingMahalanobisParams(AdaptiveHyperparameters):
    window_size: int = Field(100, ge=3, le=1_000_000)
    bias: bool = True


@dataclass(frozen=True)
class AdaptiveModelDefinition:
    model_type: str
    name: str
    import_path: str
    params_model: type[AdaptiveHyperparameters]
    feature_count: Literal["one", "two", "any"] = "any"
    complexity: Literal["low", "medium", "high"] = "medium"
    memory_usage: Literal["low", "medium", "high"] = "medium"


def _definition(
    class_name: str,
    module: str,
    params: type[AdaptiveHyperparameters],
    *,
    feature_count: Literal["one", "two", "any"] = "any",
    complexity: Literal["low", "medium", "high"] = "medium",
    memory_usage: Literal["low", "medium", "high"] = "medium",
) -> AdaptiveModelDefinition:
    snake = {
        "ASDIsolationForest": "asd_isolation_forest",
        "GADGETSVM": "gadget_svm",
        "KNN": "knn",
        "XStream": "x_stream",
        "IncrementalOneClassSVMAdaptiveKernel": (
            "incremental_one_class_svm_adaptive_kernel"
        ),
    }.get(class_name)
    if snake is None:
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    return AdaptiveModelDefinition(
        model_type=f"aberrant_{snake}",
        name=f"Aberrant {class_name}",
        import_path=f"aberrant.model.{module}.{class_name}",
        params_model=params,
        feature_count=feature_count,
        complexity=complexity,
        memory_usage=memory_usage,
    )


_UNIVARIATE_MODELS = {
    "MovingAverage": MovingUnivariateParams,
    "MovingAverageAbsoluteDeviation": MovingUnivariateParams,
    "MovingGeometricAverage": MovingGeometricAverageParams,
    "MovingHarmonicAverage": MovingUnivariateParams,
    "MovingInterquartileRange": MovingUnivariateParams,
    "MovingKurtosis": MovingUnivariateParams,
    "MovingMedian": MovingUnivariateParams,
    "MovingQuantile": MovingQuantileParams,
    "MovingSkewness": MovingUnivariateParams,
    "MovingVariance": MovingUnivariateParams,
}

ADAPTIVE_MODEL_DEFINITIONS = (
    _definition("ASDIsolationForest", "iforest", ASDIsolationForestParams),
    _definition("HalfSpaceTrees", "iforest", HalfSpaceTreesParams),
    _definition("MondrianForest", "iforest", MondrianForestParams),
    _definition("OnlineIsolationForest", "iforest", OnlineIsolationForestParams),
    _definition("RandomCutForest", "iforest", RandomCutForestParams),
    _definition(
        "StreamRandomHistogramForest",
        "iforest",
        StreamRandomHistogramForestParams,
    ),
    _definition("XStream", "iforest", XStreamParams),
    _definition("KNN", "distance", KNNParams, memory_usage="high"),
    _definition("LocalOutlierFactor", "distance", LocalOutlierFactorParams),
    _definition("GADGETSVM", "svm", GADGETSVMParams, complexity="high"),
    _definition(
        "IncrementalOneClassSVMAdaptiveKernel",
        "svm",
        AdaptiveKernelSVMParams,
        complexity="high",
    ),
    *(
        _definition(
            class_name,
            "stat",
            params,
            feature_count="one",
            complexity="low",
            memory_usage="low",
        )
        for class_name, params in _UNIVARIATE_MODELS.items()
    ),
    _definition(
        "MovingCorrelationCoefficient",
        "stat",
        MovingBivariateParams,
        feature_count="two",
        complexity="low",
        memory_usage="low",
    ),
    _definition(
        "MovingCovariance",
        "stat",
        MovingBivariateParams,
        feature_count="two",
        complexity="low",
        memory_usage="low",
    ),
    _definition(
        "MovingMahalanobisDistance",
        "stat",
        MovingMahalanobisParams,
        complexity="low",
        memory_usage="low",
    ),
)

ADAPTIVE_MODELS_BY_TYPE = {
    definition.model_type: definition for definition in ADAPTIVE_MODEL_DEFINITIONS
}
BUILTIN_ADAPTIVE_MODEL_TYPES = frozenset(ADAPTIVE_MODELS_BY_TYPE)


def validate_adaptive_model_params(
    model_type: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    try:
        definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    except KeyError as exc:
        raise ValueError(f"Unknown adaptive model type: '{model_type}'") from exc
    return definition.params_model.model_validate(params or {}).model_dump()


def minimum_model_warmup(model_type: str, params: dict[str, Any]) -> int:
    direct_fields = {
        "aberrant_asd_isolation_forest": "max_samples",
        "aberrant_half_space_trees": "window_size",
        "aberrant_stream_random_histogram_forest": "window_size",
        "aberrant_online_isolation_forest": "max_leaf_samples",
    }
    if field_name := direct_fields.get(model_type):
        return int(params[field_name])
    if model_type == "aberrant_random_cut_forest":
        warmup = int(params.get("warmup_samples") or params["sample_size"])
        return warmup + int(params["shingle_size"]) - 1
    if model_type == "aberrant_x_stream":
        return int(params["init_sample_size"]) + int(params["window_size"])
    if model_type == "aberrant_knn":
        return _knn_warmup(params)
    if model_type == "aberrant_local_outlier_factor":
        return _lof_warmup(params)
    if "window_size" in params and model_type.startswith("aberrant_moving_"):
        return int(params["window_size"])
    return 1


def _knn_warmup(params: dict[str, Any]) -> int:
    if not params["k"] <= params["warm_up"] <= params["window_size"]:
        raise ValueError("KNN requires k <= warm_up <= window_size")
    return int(params["warm_up"])


def _lof_warmup(params: dict[str, Any]) -> int:
    if params["k"] > params["window_size"]:
        raise ValueError("LocalOutlierFactor requires k <= window_size")
    return int(params["k"])
