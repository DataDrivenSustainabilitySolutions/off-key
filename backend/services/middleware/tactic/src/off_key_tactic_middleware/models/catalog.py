"""The detector catalogue shipped in RADAR, served straight from code."""

from typing import Any

from off_key_core.models import (
    ABERRANT_VERSION,
    ADAPTIVE_MODEL_FAMILY,
    ADAPTIVE_MODELS_BY_TYPE,
    ADAPTIVE_MONITORING_STRATEGY,
    STATIC_MODEL_FAMILY,
    STATIC_MONITORING_STRATEGY,
    adaptive_model_metadata,
    validate_adaptive_model_params,
)
from off_key_core.models.static import STATIC_MODELS, validate_static_model_params


def available_models() -> list[dict[str, Any]]:
    """Every executable detector with its parameter schema and defaults."""
    static = [
        {
            "model_type": model_type,
            "family": STATIC_MODEL_FAMILY,
            "name": definition.name,
            "description": (
                f"Static {definition.name} detector wrapped by conformal p-values"
            ),
            "complexity": definition.complexity,
            "memory_usage": definition.memory_usage,
            "import_paths": [definition.import_path],
            "parameter_schema": definition.parameters.model_json_schema(),
            "default_parameters": definition.parameters().model_dump(),
            "version": "1.0.0",
            "requires_special_handling": False,
            "strategy": STATIC_MONITORING_STRATEGY,
        }
        for model_type, definition in STATIC_MODELS.items()
    ]
    adaptive = [
        {
            "model_type": model_type,
            "family": ADAPTIVE_MODEL_FAMILY,
            "name": definition["name"],
            "description": "Online score-then-learn detector from Aberrant",
            "complexity": "unknown",
            "memory_usage": definition["default_capabilities"]["state"],
            "import_paths": [definition["import_path"]],
            "parameter_schema": definition["parameter_schema"],
            "default_parameters": definition["default_parameters"],
            "version": ABERRANT_VERSION,
            "requires_special_handling": False,
            "strategy": ADAPTIVE_MONITORING_STRATEGY,
            **adaptive_model_metadata(model_type),
        }
        for model_type, definition in ADAPTIVE_MODELS_BY_TYPE.items()
    ]
    return static + adaptive


def validate_model_params(
    model_type: str, params: dict[str, Any] | None, *, family: str
) -> dict[str, Any]:
    """Merge a detector's defaults with ``params`` and validate the result."""
    if family == ADAPTIVE_MODEL_FAMILY:
        definition = ADAPTIVE_MODELS_BY_TYPE.get(model_type)
        if definition is None:
            raise ValueError(f"Unknown model type: '{model_type}'")
        merged = {**definition["default_parameters"], **(params or {})}
        return validate_adaptive_model_params(model_type, merged)
    if family != STATIC_MODEL_FAMILY:
        raise ValueError(f"Unsupported executable model family: {family}")
    definition = STATIC_MODELS.get(model_type)
    if definition is None:
        raise ValueError(f"Unknown model type: '{model_type}'")
    merged = {**definition.parameters().model_dump(), **(params or {})}
    return validate_static_model_params(model_type, merged)
