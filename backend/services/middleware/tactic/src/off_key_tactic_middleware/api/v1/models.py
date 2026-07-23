"""
TACTIC API endpoints for ML model management.

Provides REST API for managing model registry and model instances.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ...models.registry import ModelRegistryService
from ...provider import get_model_registry_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


# Request/Response models
class ModelInfo(BaseModel):
    """Model information response."""

    model_type: str = Field(..., description="Model type identifier")
    family: str = Field(
        ...,
        description="Model family (e.g., 'distance', 'forest', 'svm')",
    )
    name: str = Field(..., description="Human-readable model name")
    description: str | None = Field(None, description="Model description")
    complexity: str | None = Field(None, description="Computational complexity")
    memory_usage: str | None = Field(None, description="Memory usage level")
    strategy: str = Field(
        default="static_baseline",
        description="Executable static monitoring lane",
    )
    import_paths: list[str] = Field(..., description="Python import paths to try")
    parameter_schema: dict[str, Any] = Field(
        ..., description="JSON schema for parameters"
    )
    default_parameters: dict[str, Any] = Field(
        ..., description="Default parameter values"
    )
    version: str = Field(..., description="Model version")
    requires_special_handling: bool = Field(
        ..., description="Requires custom instantiation logic"
    )


class ModelInstanceRequest(BaseModel):
    """Request to create a model instance."""

    model_type: str = Field(..., description="Model type identifier")
    parameters: dict[str, Any] | None = Field(None, description="Model parameters")


class ModelValidationRequest(BaseModel):
    """Request to validate model parameters."""

    model_type: str = Field(..., description="Model type identifier")
    parameters: dict[str, Any] | None = Field(
        None, description="Parameters to validate"
    )


class ModelValidationResponse(BaseModel):
    """Model parameter validation response."""

    valid: bool = Field(..., description="Whether parameters are valid")
    validated_parameters: dict[str, Any] | None = Field(
        None, description="Validated parameters with defaults"
    )
    error: str | None = Field(None, description="Validation error message")


@router.get("/", response_model=list[ModelInfo])
async def list_models(
    strategy: str | None = Query(default=None),
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> list[ModelInfo]:
    """
    Get list of all available models.

    Returns comprehensive information about each model including
    parameter schemas and metadata.
    """
    try:
        models = model_registry.get_available_models()
        if strategy:
            models = [model for model in models if model.get("strategy") == strategy]
        return [ModelInfo(**model) for model in models]
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve models")


@router.get("/info/{model_type}", response_model=ModelInfo)
async def get_model_info(
    model_type: str,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> ModelInfo:
    """
    Get detailed information about a specific model.

    Args:
        model_type: The model type identifier

    Returns:
        Detailed model information including schema and defaults
    """
    try:
        models = model_registry.get_available_models()
        model = next((m for m in models if m["model_type"] == model_type), None)

        if not model:
            raise HTTPException(
                status_code=404, detail=f"Model '{model_type}' not found"
            )

        return ModelInfo(**model)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model info for '{model_type}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve model information"
        )


@router.post("/validate", response_model=ModelValidationResponse)
async def validate_model_parameters(
    request: ModelValidationRequest,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> ModelValidationResponse:
    """
    Validate model parameters against the model's schema.

    Args:
        request: Model type and parameters to validate

    Returns:
        Validation result with validated parameters or error message
    """
    try:
        validated_params = model_registry.validate_model_params(
            request.model_type, request.parameters
        )
        return ModelValidationResponse(
            valid=True, validated_parameters=validated_params
        )
    except ValueError as e:
        return ModelValidationResponse(valid=False, error=str(e))
    except Exception as e:
        logger.error(f"Failed to validate parameters for '{request.model_type}': {e}")
        raise HTTPException(status_code=500, detail="Parameter validation failed")


@router.post("/create-instance", status_code=200)
async def create_model_instance(
    request: ModelInstanceRequest,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> dict[str, Any]:
    """
    Create and initialize a model instance.

    Note: This endpoint validates parameters and confirms the model can be instantiated,
    but doesn't return the actual instance (which isn't JSON-serializable).
    Use this for validation before actual model creation in RADAR services.

    Args:
        request: Model type and parameters

    Returns:
        Success confirmation with validated parameters
    """
    try:
        validation_result = model_registry.validate_model_instantiation(
            request.model_type, request.parameters
        )
        instantiated = validation_result["instantiated"]
        runtime_owner = validation_result["runtime_owner"]

        return {
            "success": True,
            "message": (
                f"Model '{request.model_type}' created successfully"
                if instantiated
                else (
                    f"Model '{request.model_type}' parameters validated; "
                    "instantiation is deferred to the RADAR runtime"
                )
            ),
            "model_type": request.model_type,
            "validated_parameters": validation_result["validated_parameters"],
            "instantiated": instantiated,
            "runtime_owner": runtime_owner,
        }
    except ValueError:
        logger.warning(
            "Model validation failed for '%s'",
            request.model_type,
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail="Model validation failed. Check model type and parameters.",
        )
    except ImportError:
        logger.exception("Model dependency import failed for '%s'", request.model_type)
        raise HTTPException(
            status_code=422,
            detail="Model dependencies are not available.",
        )
    except Exception:
        logger.exception("Failed to create model instance '%s'", request.model_type)
        raise HTTPException(status_code=500, detail="Model creation failed")


@router.get("/categories/models", response_model=list[str])
async def get_model_categories(
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> list[str]:
    """
    Get list of unique model families.

    Returns:
        List of available model families (e.g., ['distance', 'forest', 'svm'])
    """
    try:
        models = model_registry.get_available_models()
        families = list({m["family"] for m in models})
        return sorted(families)
    except Exception as e:
        logger.error(f"Failed to get model families: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model families")


@router.get("/health")
async def model_registry_health(
    response: Response,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> dict[str, Any]:
    """
    Health check for model registry service.

    Returns:
        Health status and basic statistics
    """
    try:
        models = model_registry.get_available_models()
        return {
            "status": "healthy",
            "models_available": len(models),
            "total_components": len(models),
        }
    except Exception:
        logger.exception("Model registry health check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy", "error": "Health check failed"}
