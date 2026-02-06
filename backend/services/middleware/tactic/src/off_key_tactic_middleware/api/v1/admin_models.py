"""
TACTIC Admin API for ML Model Registry Management.

Provides admin endpoints for dynamically adding, updating, and managing models.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator

from ...domain import DomainError, ConflictError, NotFoundError, InfrastructureError
from ...models.registry import ModelRegistryService
from ...provider import get_model_registry_service, get_model_registry_admin_service
from ...services.admin_models import ModelRegistryAdminService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/models", tags=["admin", "models"])


def _raise_http_from_domain(error: DomainError) -> None:
    """Map domain errors to HTTP response codes."""
    if isinstance(error, ConflictError):
        raise HTTPException(status_code=409, detail=str(error))
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, InfrastructureError):
        raise HTTPException(status_code=500, detail="Failed to process request")

    raise HTTPException(status_code=500, detail="Unexpected domain error")


# Request/Response models for admin operations
class CreateModelRequest(BaseModel):
    """Request to create a new model in registry."""

    model_type: str = Field(..., description="Unique model type identifier")
    category: str = Field(..., description="'model' or 'preprocessor'")
    family: str = Field(
        ...,
        description="Domain family (e.g., model: 'forest'; preprocessor: 'scaling')",
    )
    name: str = Field(..., description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
    complexity: Optional[str] = Field("medium", description="Computational complexity")
    memory_usage: Optional[str] = Field("medium", description="Memory usage level")
    import_paths: List[str] = Field(..., description="Python import paths to try")
    parameter_schema: Dict[str, Any] = Field(
        ..., description="JSON schema for parameters"
    )
    default_parameters: Dict[str, Any] = Field(
        default_factory=dict, description="Default parameter values"
    )
    version: str = Field(default="1.0.0", description="Model version")
    requires_special_handling: bool = Field(
        default=False, description="Requires custom instantiation logic"
    )

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"model", "preprocessor"}:
            raise ValueError("category must be either 'model' or 'preprocessor'")
        return normalized

    @field_validator("family")
    @classmethod
    def validate_family(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("family must not be empty")
        return normalized


class UpdateModelRequest(BaseModel):
    """Request to update an existing model."""

    name: Optional[str] = Field(None, description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
    family: Optional[str] = Field(
        None,
        description="Domain family (e.g., model: 'forest'; preprocessor: 'scaling')",
    )
    complexity: Optional[str] = Field(None, description="Computational complexity")
    memory_usage: Optional[str] = Field(None, description="Memory usage level")
    import_paths: Optional[List[str]] = Field(
        None, description="Python import paths to try"
    )
    parameter_schema: Optional[Dict[str, Any]] = Field(
        None, description="JSON schema for parameters"
    )
    default_parameters: Optional[Dict[str, Any]] = Field(
        None, description="Default parameter values"
    )
    version: Optional[str] = Field(None, description="Model version")
    is_active: Optional[bool] = Field(None, description="Whether model is active")
    requires_special_handling: Optional[bool] = Field(
        None, description="Requires custom instantiation logic"
    )

    @field_validator("family")
    @classmethod
    def validate_family(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("family must not be empty")
        return normalized


class ModelRegistryResponse(BaseModel):
    """Full model registry entry response."""

    id: int
    model_type: str
    category: str
    family: str
    name: str
    description: Optional[str]
    complexity: Optional[str]
    memory_usage: Optional[str]
    import_paths: List[str]
    parameter_schema: Dict[str, Any]
    default_parameters: Dict[str, Any]
    version: str
    is_active: bool
    requires_special_handling: bool
    created_at: str
    updated_at: str


@router.post("/", response_model=ModelRegistryResponse)
async def create_model(
    request: CreateModelRequest,
    service: ModelRegistryAdminService = Depends(get_model_registry_admin_service),
) -> ModelRegistryResponse:
    """
    Create a new model in the registry.

    This allows adding new models dynamically without code changes.
    """
    try:
        return ModelRegistryResponse(
            **service.create_model(payload=request.model_dump()),
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.put("/{model_type}", response_model=ModelRegistryResponse)
async def update_model(
    model_type: str,
    request: UpdateModelRequest,
    service: ModelRegistryAdminService = Depends(get_model_registry_admin_service),
) -> ModelRegistryResponse:
    """
    Update an existing model in the registry.

    Allows updating model metadata, parameters, or activation status.
    """
    try:
        return ModelRegistryResponse(
            **service.update_model(
                model_type=model_type,
                update_data=request.model_dump(exclude_unset=True),
            ),
        )
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.delete("/{model_type}")
async def delete_model(
    model_type: str,
    service: ModelRegistryAdminService = Depends(get_model_registry_admin_service),
) -> Dict[str, str]:
    """
    Delete (deactivate) a model from the registry.

    Actually sets is_active=False rather than hard deleting to preserve history.
    """
    try:
        return service.deactivate_model(model_type=model_type)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/", response_model=List[ModelRegistryResponse])
async def list_all_models(
    include_inactive: bool = False,
    category: Optional[str] = None,
    service: ModelRegistryAdminService = Depends(get_model_registry_admin_service),
) -> List[ModelRegistryResponse]:
    """
    List all models in registry, including inactive ones.

    Useful for admin interface showing complete model inventory.
    """
    try:
        models = service.list_models(
            include_inactive=include_inactive,
            category=category,
        )
        return [ModelRegistryResponse(**model) for model in models]
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.post("/{model_type}/test")
async def test_model_instantiation(
    model_type: str,
    test_parameters: Optional[Dict[str, Any]] = None,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> Dict[str, Any]:
    """
    Test that a model can be instantiated with given parameters.

    Useful for validating new model definitions before deployment.
    """
    try:
        # Test parameter validation
        validated_params = model_registry.validate_model_params(
            model_type, test_parameters or {}
        )

        # Test model instantiation (but don't return the instance)
        model_registry.create_model_instance(model_type, validated_params)

        return {
            "success": True,
            "message": f"Model '{model_type}' instantiated successfully",
            "validated_parameters": validated_params,
        }

    except ValueError as e:
        return {"success": False, "error": "validation_error", "message": str(e)}
    except ImportError as e:
        return {
            "success": False,
            "error": "import_error",
            "message": f"Cannot import model dependencies: {e}",
        }
    except Exception as e:
        logger.error(f"Model test failed for '{model_type}': {e}")
        return {"success": False, "error": "instantiation_error", "message": str(e)}
