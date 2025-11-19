"""
Model Registry for ONAD Anomaly Detection Models.

Provides a centralized registry that maps model type identifiers to their:
- Import paths (for dynamic loading)
- Hyperparameter schemas (for validation)
- Metadata (descriptions, requirements)

This design enables:
1. Easy addition of new models without code changes in multiple files
2. Automatic API documentation generation
3. Runtime validation of model parameters
4. Future version compatibility tracking

Usage:
    from off_key_core.models import MODEL_REGISTRY, get_model_class

    # Get model class dynamically
    model_class = get_model_class("knn")
    model = model_class(n_neighbors=10, window_size=500)

    # Validate parameters
    validated = validate_model_params("knn", {"n_neighbors": 10})
"""

import importlib
import logging
from typing import Any, Dict, Type, Optional

from .schemas import (
    ModelHyperparameters,
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    HalfSpaceTrees,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Model Registry Definition
# =============================================================================

MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # -------------------------------------------------------------------------
    # Distance-based Models
    # -------------------------------------------------------------------------
    "knn": {
        "import_path": "onad.models.incremental_knn.IncrementalKNN",
        "params_schema": IncrementalKNNParams,
        "description": "Incremental K-Nearest Neighbors for streaming anomaly detection",  # noqa
        "category": "distance",
        "complexity": "low",
        "memory_usage": "medium",  # Stores window_size points
    },
    # -------------------------------------------------------------------------
    # Forest-based Models
    # -------------------------------------------------------------------------
    "isolation_forest": {
        "import_path": "onad.models.online_isolation_forest.OnlineIsolationForest",
        "params_schema": OnlineIsolationForestParams,
        "description": "Online Isolation Forest for streaming anomaly detection",
        "category": "forest",
        "complexity": "medium",
        "memory_usage": "medium",
    },
    "half_space_trees": {
        "import_path": "onad.models.half_space_trees.HalfSpaceTrees",
        "params_schema": HalfSpaceTrees,
        "description": "Half-Space Trees - fast streaming anomaly detection via random partitioning",  # noqa
        "category": "forest",
        "complexity": "low",
        "memory_usage": "low",
    },
    # -------------------------------------------------------------------------
    # SVM-based Models
    # -------------------------------------------------------------------------
    "adaptive_svm": {
        "import_path": "onad.models.incremental_one_class_svm.IncrementalOneClassSVMAdaptiveKernel",  # noqa
        "params_schema": AdaptiveSVMParams,
        "description": "Adaptive One-Class SVM with incremental kernel updates",
        "category": "svm",
        "complexity": "high",
        "memory_usage": "high",
    },
}


# =============================================================================
# Registry Access Functions
# =============================================================================


def get_model_class(model_type: str) -> Type:
    """
    Dynamically import and return the model class.

    Args:
        model_type: The model type identifier (e.g., "knn", "isolation_forest")

    Returns:
        The model class ready for instantiation

    Raises:
        ValueError: If model_type is not in registry
        ImportError: If the model module cannot be imported
    """
    if model_type not in MODEL_REGISTRY:
        available = ", ".join(MODEL_REGISTRY.keys())
        raise ValueError(
            f"Unknown model type: '{model_type}'. Available models: {available}"
        )

    config = MODEL_REGISTRY[model_type]
    import_path = config["import_path"]

    try:
        module_path, class_name = import_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        model_class = getattr(module, class_name)
        return model_class
    except ImportError as e:
        logger.error(f"Failed to import model '{model_type}' from '{import_path}': {e}")
        raise ImportError(
            f"Cannot import model '{model_type}'. "
            f"Ensure onad is installed: pip install onad"
        ) from e
    except AttributeError as e:
        logger.error(f"Model class not found in module: {e}")
        raise ImportError(
            f"Model class '{class_name}' not found in '{module_path}'"
        ) from e


def get_model_params_schema(model_type: str) -> Type[ModelHyperparameters]:
    """
    Get the Pydantic schema for a model's hyperparameters.

    Args:
        model_type: The model type identifier

    Returns:
        The Pydantic model class for parameter validation
    """
    if model_type not in MODEL_REGISTRY:
        available = ", ".join(MODEL_REGISTRY.keys())
        raise ValueError(
            f"Unknown model type: '{model_type}'. Available models: {available}"
        )

    return MODEL_REGISTRY[model_type]["params_schema"]


def validate_model_params(
    model_type: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Validate and normalize model parameters.

    Args:
        model_type: The model type identifier
        params: Raw parameters dict (can include extra/missing params)

    Returns:
        Validated parameters with defaults applied

    Raises:
        ValueError: If model_type is unknown or params are invalid
    """
    schema = get_model_params_schema(model_type)
    params = params or {}

    try:
        validated = schema(**params)
        return validated.model_dump()
    except Exception as e:
        raise ValueError(f"Invalid parameters for model '{model_type}': {e}") from e


def get_available_models() -> Dict[str, Dict[str, Any]]:
    """
    Get information about all available models.

    Returns:
        Dictionary with model metadata and JSON schemas for parameters
    """
    result = {}
    for model_type, config in MODEL_REGISTRY.items():
        schema = config["params_schema"]
        result[model_type] = {
            "description": config.get("description", ""),
            "category": config.get("category", "unknown"),
            "complexity": config.get("complexity", "unknown"),
            "memory_usage": config.get("memory_usage", "unknown"),
            "parameters": schema.model_json_schema(),
        }
    return result


def create_model_instance(
    model_type: str, params: Optional[Dict[str, Any]] = None
) -> Any:
    """
    Create a model instance with validated parameters.

    This is a convenience function that combines get_model_class
    and validate_model_params.

    Args:
        model_type: The model type identifier
        params: Model hyperparameters

    Returns:
        Instantiated model ready for use
    """
    model_class = get_model_class(model_type)
    validated_params = validate_model_params(model_type, params)
    return model_class(**validated_params)
