"""
TACTIC API endpoints for ML model management.

Provides REST API for managing model registry and model instances.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...models.registry import model_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


# Request/Response models
class ModelInfo(BaseModel):
    """Model information response."""
    model_type: str = Field(..., description="Model type identifier")
    name: str = Field(..., description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
    complexity: Optional[str] = Field(None, description="Computational complexity")
    memory_usage: Optional[str] = Field(None, description="Memory usage level")
    import_paths: List[str] = Field(..., description="Python import paths to try")
    parameter_schema: Dict[str, Any] = Field(..., description="JSON schema for parameters")
    default_parameters: Dict[str, Any] = Field(..., description="Default parameter values")
    version: str = Field(..., description="Model version")
    requires_special_handling: bool = Field(..., description="Requires custom instantiation logic")


class PreprocessorInfo(BaseModel):
    """Preprocessor information response."""
    model_type: str = Field(..., description="Preprocessor type identifier")
    name: str = Field(..., description="Human-readable preprocessor name")
    description: Optional[str] = Field(None, description="Preprocessor description")
    import_paths: List[str] = Field(..., description="Python import paths to try")
    parameter_schema: Dict[str, Any] = Field(..., description="JSON schema for parameters")
    default_parameters: Dict[str, Any] = Field(..., description="Default parameter values")
    version: str = Field(..., description="Preprocessor version")
    requires_special_handling: bool = Field(..., description="Requires custom instantiation logic")


class ModelInstanceRequest(BaseModel):
    """Request to create a model instance."""
    model_type: str = Field(..., description="Model type identifier")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Model parameters")


class ModelValidationRequest(BaseModel):
    """Request to validate model parameters."""
    model_type: str = Field(..., description="Model type identifier")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Parameters to validate")


class ModelValidationResponse(BaseModel):
    """Model parameter validation response."""
    valid: bool = Field(..., description="Whether parameters are valid")
    validated_parameters: Optional[Dict[str, Any]] = Field(None, description="Validated parameters with defaults")
    error: Optional[str] = Field(None, description="Validation error message")


@router.get("/", response_model=List[ModelInfo])
async def list_models() -> List[ModelInfo]:
    """
    Get list of all available models.

    Returns comprehensive information about each model including
    parameter schemas and metadata.
    """
    try:
        models = model_registry.get_available_models()
        return [ModelInfo(**model) for model in models]
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve models")


@router.get("/preprocessors", response_model=List[PreprocessorInfo])
async def list_preprocessors() -> List[PreprocessorInfo]:
    """
    Get list of all available preprocessors.

    Returns comprehensive information about each preprocessor including
    parameter schemas and metadata.
    """
    try:
        preprocessors = model_registry.get_available_preprocessors()
        return [PreprocessorInfo(**prep) for prep in preprocessors]
    except Exception as e:
        logger.error(f"Failed to list preprocessors: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve preprocessors")


@router.get("/{model_type}", response_model=ModelInfo)
async def get_model_info(model_type: str) -> ModelInfo:
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
            # Try preprocessors
            preprocessors = model_registry.get_available_preprocessors()
            model = next((p for p in preprocessors if p["model_type"] == model_type), None)

        if not model:
            raise HTTPException(status_code=404, detail=f"Model '{model_type}' not found")

        return ModelInfo(**model)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model info for '{model_type}': {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model information")


@router.post("/validate", response_model=ModelValidationResponse)
async def validate_model_parameters(request: ModelValidationRequest) -> ModelValidationResponse:
    """
    Validate model parameters against the model's schema.

    Args:
        request: Model type and parameters to validate

    Returns:
        Validation result with validated parameters or error message
    """
    try:
        validated_params = model_registry.validate_model_params(
            request.model_type,
            request.parameters
        )
        return ModelValidationResponse(
            valid=True,
            validated_parameters=validated_params
        )
    except ValueError as e:
        return ModelValidationResponse(
            valid=False,
            error=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to validate parameters for '{request.model_type}': {e}")
        raise HTTPException(status_code=500, detail="Parameter validation failed")


@router.post("/create-instance", status_code=200)
async def create_model_instance(request: ModelInstanceRequest) -> Dict[str, Any]:
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
        # Validate parameters first
        validated_params = model_registry.validate_model_params(
            request.model_type,
            request.parameters
        )

        # Test that the model can be instantiated (but don't return it)
        model_registry.create_model_instance(request.model_type, validated_params)

        return {
            "success": True,
            "message": f"Model '{request.model_type}' created successfully",
            "model_type": request.model_type,
            "validated_parameters": validated_params
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ImportError as e:
        raise HTTPException(status_code=422, detail=f"Model dependencies not available: {e}")
    except Exception as e:
        logger.error(f"Failed to create model instance '{request.model_type}': {e}")
        raise HTTPException(status_code=500, detail="Model creation failed")


@router.get("/categories/models", response_model=List[str])
async def get_model_categories() -> List[str]:
    """
    Get list of unique model categories.

    Returns:
        List of available model categories (e.g., ['distance', 'forest', 'svm'])
    """
    try:
        models = model_registry.get_available_models()
        categories = list({m.get("complexity", "unknown") for m in models})
        return sorted(categories)
    except Exception as e:
        logger.error(f"Failed to get model categories: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve categories")


@router.get("/health")
async def model_registry_health() -> Dict[str, Any]:
    """
    Health check for model registry service.

    Returns:
        Health status and basic statistics
    """
    try:
        models = model_registry.get_available_models()
        preprocessors = model_registry.get_available_preprocessors()

        return {
            "status": "healthy",
            "models_available": len(models),
            "preprocessors_available": len(preprocessors),
            "total_components": len(models) + len(preprocessors)
        }
    except Exception as e:
        logger.error(f"Model registry health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e)
        }