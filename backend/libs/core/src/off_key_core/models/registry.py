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
from typing import Any, Dict, Type, Optional, List

from .schemas import (
    ModelHyperparameters,
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    MondrianIsolationForestParams,
    StandardScalerParams,
    IncrementalPCAParams,
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
        "import_paths": ["onad.model.distance.knn.KNN"],
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
        "import_paths": ["onad.model.iforest.online.OnlineIsolationForest"],
        "params_schema": OnlineIsolationForestParams,
        "description": "Online Isolation Forest for streaming anomaly detection",
        "category": "forest",
        "complexity": "medium",
        "memory_usage": "medium",
    },
    "mondrian_forest": {
        "import_paths": ["onad.model.iforest.mondrian.MondrianForest"],
        "params_schema": MondrianIsolationForestParams,
        "description": "Mondrian Forest - fast streaming anomaly detection",
        "category": "forest",
        "complexity": "low",
        "memory_usage": "low",
    },
    # -------------------------------------------------------------------------
    # SVM-based Models
    # -------------------------------------------------------------------------
    "adaptive_svm": {
        "import_paths": [
            "onad.model.svm.adaptive.IncrementalOneClassSVMAdaptiveKernel"
        ],
        "params_schema": AdaptiveSVMParams,
        "description": "Adaptive One-Class SVM with incremental kernel updates",
        "category": "svm",
        "complexity": "high",
        "memory_usage": "high",
    },
}

PREPROCESSOR_REGISTRY: Dict[str, Dict[str, Any]] = {
    "standard_scaler": {
        "import_paths": ["onad.transform.preprocessing.scaler.StandardScaler"],
        "params_schema": StandardScalerParams,
        "description": "Standardize features by removing mean and scaling to unit var",
    },
    "pca": {
        "import_paths": ["onad.transform.projection.incremental_pca.IncrementalPCA"],
        "params_schema": IncrementalPCAParams,
        "description": "Incremental PCA for dimensionality reduction on streams",
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
    import_paths = config.get("import_paths") or [config.get("import_path")]
    import_paths = [p for p in import_paths if p]  # Filter None values
    errors = []

    for import_path in import_paths:
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            model_class = getattr(module, class_name)
            return model_class
        except (ImportError, AttributeError, ModuleNotFoundError) as e:
            errors.append(f"{import_path}: {e}")
            continue

    error_msg = "; ".join(errors) if errors else "unknown"
    logger.error(
        f"Failed to import model '{model_type}' from any known path: {error_msg}"
    )
    raise ImportError(
        f"Cannot import model '{model_type}'. "
        f"Ensure onad is installed and compatible. Tried: {import_paths}"
    )


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
        return validated.model_dump(mode="json")
    except Exception as e:
        raise ValueError(f"Invalid parameters for model '{model_type}': {e}") from e


def get_preprocessor_class(step_type: str) -> Type:
    """Dynamically import and return a preprocessor class."""
    if step_type not in PREPROCESSOR_REGISTRY:
        available = ", ".join(PREPROCESSOR_REGISTRY.keys())
        raise ValueError(
            f"Unknown preprocessor type: '{step_type}'. Available: {available}"
        )

    config = PREPROCESSOR_REGISTRY[step_type]
    import_paths = config.get("import_paths") or [config.get("import_path")]
    import_paths = [p for p in import_paths if p]  # Filter None values
    errors = []

    for import_path in import_paths:
        try:
            module_path, class_name = import_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            return cls
        except (ImportError, AttributeError, ModuleNotFoundError) as e:
            errors.append(f"{import_path}: {e}")
            continue

    error_msg = "; ".join(errors) if errors else "unknown"
    logger.error(
        f"Failed to import preprocessor '{step_type}' from any known path: {error_msg}"
    )
    raise ImportError(
        f"Cannot import preprocessor '{step_type}'. "
        f"Ensure onad is installed and compatible. Tried: {import_paths}"
    )


def validate_preprocessing_steps(
    steps: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Validate and normalize preprocessing steps."""
    if not steps:
        return []

    validated_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each preprocessing step must be an object")
        step_type = step.get("type")
        params = step.get("params") or {}
        if step_type not in PREPROCESSOR_REGISTRY:
            available = ", ".join(PREPROCESSOR_REGISTRY.keys())
            raise ValueError(
                f"Unknown preprocessor type: '{step_type}'. Available: {available}"
            )
        schema = PREPROCESSOR_REGISTRY[step_type]["params_schema"]
        try:
            validated_params = schema(**params).model_dump(mode="json")
        except Exception as e:
            raise ValueError(
                f"Invalid parameters for preprocessor '{step_type}': {e}"
            ) from e
        validated_steps.append({"type": step_type, "params": validated_params})

    return validated_steps


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


def get_available_preprocessors() -> Dict[str, Dict[str, Any]]:
    """Get information about available preprocessing steps."""
    result = {}
    for step_type, config in PREPROCESSOR_REGISTRY.items():
        schema = config["params_schema"]
        result[step_type] = {
            "description": config.get("description", ""),
            "parameters": schema.model_json_schema(),
        }
    return result


def _create_knn_model(validated_params: Dict[str, Any]) -> Any:
    """
    Create KNN model with FaissSimilaritySearchEngine.

    KNN in ONAD requires a similarity_engine instance. This factory
    creates the engine from the window_size and warm_up params.

    Args:
        validated_params: Validated parameters including k, window_size, warm_up

    Returns:
        Configured KNN model instance
    """
    try:
        from onad.utils.similar.faiss_engine import FaissSimilaritySearchEngine
        from onad.model.distance.knn import KNN
    except ImportError as e:
        logger.error(f"Failed to import KNN dependencies: {e}")
        raise ImportError(
            "Cannot import KNN model. Ensure onad is installed with FAISS support."
        ) from e

    # Work with a copy to avoid mutating the input
    params = validated_params.copy()

    # Extract params for similarity engine
    window_size = params.pop("window_size", 1000)
    warm_up = params.pop("warm_up", 50)
    k = params.get("k", 5)

    # Create similarity engine
    similarity_engine = FaissSimilaritySearchEngine(
        window_size=window_size,
        warm_up=warm_up,
    )

    # Create KNN model with similarity engine
    return KNN(k=k, similarity_engine=similarity_engine)


def create_model_instance(
    model_type: str, params: Optional[Dict[str, Any]] = None
) -> Any:
    """
    Create a model instance with validated parameters.

    This is a convenience function that combines get_model_class
    and validate_model_params. It handles special cases like KNN
    which requires a similarity engine.

    Args:
        model_type: The model type identifier
        params: Model hyperparameters

    Returns:
        Instantiated model ready for use
    """
    validated_params = validate_model_params(model_type, params)

    # Special case: KNN requires a similarity engine
    if model_type == "knn":
        return _create_knn_model(validated_params)

    # Standard case: direct instantiation
    model_class = get_model_class(model_type)
    return model_class(**validated_params)
