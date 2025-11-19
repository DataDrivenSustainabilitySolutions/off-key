"""
Off-Key Core Library

Shared components for the Off-Key telemetry monitoring platform.
Provides common functionality for database models, schemas, configuration,
and external API clients.
"""

__version__ = "0.1.0"

# Model registry exports for anomaly detection
from .models import (
    MODEL_REGISTRY,
    get_model_class,
    get_model_params_schema,
    get_available_models,
    validate_model_params,
)

__all__ = [
    "MODEL_REGISTRY",
    "get_model_class",
    "get_model_params_schema",
    "get_available_models",
    "validate_model_params",
]
