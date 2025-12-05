"""
Model Registry Module

Provides a centralized registry for anomaly detection models with their
hyperparameter schemas for validation and documentation.
"""

from .registry import (
    MODEL_REGISTRY,
    PREPROCESSOR_REGISTRY,
    get_model_class,
    get_model_params_schema,
    get_available_models,
    validate_model_params,
    get_preprocessor_class,
    validate_preprocessing_steps,
    get_available_preprocessors,
    create_model_instance,
)
from .schemas import (
    ModelHyperparameters,
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    MondrianIsolationForestParams,
    PreprocessingStep,
    StandardScalerParams,
    IncrementalPCAParams,
)

__all__ = [
    "MODEL_REGISTRY",
    "PREPROCESSOR_REGISTRY",
    "get_model_class",
    "get_model_params_schema",
    "get_available_models",
    "validate_model_params",
    "get_preprocessor_class",
    "validate_preprocessing_steps",
    "get_available_preprocessors",
    "create_model_instance",
    "ModelHyperparameters",
    "IncrementalKNNParams",
    "OnlineIsolationForestParams",
    "AdaptiveSVMParams",
    "MondrianIsolationForestParams",
    "PreprocessingStep",
    "StandardScalerParams",
    "IncrementalPCAParams",
]
