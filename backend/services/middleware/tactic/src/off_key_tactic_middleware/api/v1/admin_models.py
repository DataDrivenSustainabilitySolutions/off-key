"""
TACTIC Admin API for ML Model Registry Management.

Manages metadata, defaults, and activation for models shipped in RADAR.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...domain import DomainError, InfrastructureError, NotFoundError, ValidationError
from ...models.registry import ModelRegistryService
from ...provider import get_model_registry_admin_service, get_model_registry_service
from ...services.admin_models import ModelRegistryAdminService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/models", tags=["admin", "models"])


def _raise_http_from_domain(error: DomainError) -> None:
    """Map domain errors to HTTP response codes."""
    if isinstance(error, ValidationError):
        raise HTTPException(status_code=422, detail=str(error))
    if isinstance(error, NotFoundError):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, InfrastructureError):
        raise HTTPException(status_code=500, detail="Failed to process request")

    raise HTTPException(status_code=500, detail="Unexpected domain error")


class UpdateModelRequest(BaseModel):
    """Administrator-owned metadata; executable definitions belong to the runtime."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    complexity: str | None = None
    memory_usage: str | None = None
    default_parameters: dict[str, Any] | None = None
    is_active: bool | None = None

    @field_validator("name", "default_parameters", "is_active")
    @classmethod
    def reject_explicit_null(cls, value):
        if value is None:
            raise ValueError("This field cannot be null; omit it to keep its current value")
        return value


class ModelRegistryResponse(BaseModel):
    """Full model registry entry response."""

    id: int
    model_type: str
    category: str
    family: str
    name: str
    description: str | None
    complexity: str | None
    memory_usage: str | None
    import_paths: list[str]
    parameter_schema: dict[str, Any]
    default_parameters: dict[str, Any]
    version: str
    is_active: bool
    requires_special_handling: bool
    created_at: str
    updated_at: str


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
) -> dict[str, str]:
    """
    Delete (deactivate) a model from the registry.

    Actually sets is_active=False rather than hard deleting to preserve history.
    """
    try:
        return service.deactivate_model(model_type=model_type)
    except DomainError as exc:
        _raise_http_from_domain(exc)


@router.get("/", response_model=list[ModelRegistryResponse])
async def list_all_models(
    include_inactive: bool = False,
    category: str | None = None,
    service: ModelRegistryAdminService = Depends(get_model_registry_admin_service),
) -> list[ModelRegistryResponse]:
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
    test_parameters: dict[str, Any] | None = None,
    model_registry: ModelRegistryService = Depends(get_model_registry_service),
) -> dict[str, Any]:
    """
    Validate parameters against the catalog shipped with the RADAR runtime.
    """
    try:
        validation_result = model_registry.validate_model_instantiation(
            model_type, test_parameters or {}
        )
        instantiated = validation_result["instantiated"]
        runtime_owner = validation_result["runtime_owner"]

        return {
            "success": True,
            "message": (
                f"Model '{model_type}' instantiated successfully"
                if instantiated
                else (
                    f"Model '{model_type}' parameters validated; "
                    "instantiation is deferred to the RADAR runtime"
                )
            ),
            "validated_parameters": validation_result["validated_parameters"],
            "instantiated": instantiated,
            "runtime_owner": runtime_owner,
        }

    except ValueError:
        logger.warning(
            "Model validation failed for '%s'",
            model_type,
            exc_info=True,
        )
        return {
            "success": False,
            "error": "validation_error",
            "message": "Model validation failed. Check model type and parameters.",
        }
    except ImportError:
        logger.exception("Model dependency import failed for '%s'", model_type)
        return {
            "success": False,
            "error": "import_error",
            "message": "Model dependencies are not available.",
        }
    except Exception:
        logger.exception("Model test failed for '%s'", model_type)
        return {
            "success": False,
            "error": "instantiation_error",
            "message": "Model instantiation failed due to an internal error",
        }
