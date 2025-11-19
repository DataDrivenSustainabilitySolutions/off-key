"""
Model Registry Module

Provides a centralized registry for anomaly detection models with their
hyperparameter schemas for validation and documentation.
"""

from .registry import (
    MODEL_REGISTRY,
    get_model_class,
    get_model_params_schema,
    get_available_models,
    validate_model_params,
)
from .schemas import (
    ModelHyperparameters,
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    HalfSpaceTrees,
)

__all__ = [
    "MODEL_REGISTRY",
    "get_model_class",
    "get_model_params_schema",
    "get_available_models",
    "validate_model_params",
    "ModelHyperparameters",
    "IncrementalKNNParams",
    "OnlineIsolationForestParams",
    "AdaptiveSVMParams",
    "HalfSpaceTrees",
]
