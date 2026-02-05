"""
TACTIC Admin API for ML Model Registry Management.

Provides admin endpoints for dynamically adding, updating, and managing models.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from off_key_core.db.models import ModelRegistry
from off_key_core.db.base import get_db_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/models", tags=["admin", "models"])


# Request/Response models for admin operations
class CreateModelRequest(BaseModel):
    """Request to create a new model in registry."""

    model_type: str = Field(..., description="Unique model type identifier")
    category: str = Field(..., description="'model' or 'preprocessor'")
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


class UpdateModelRequest(BaseModel):
    """Request to update an existing model."""

    name: Optional[str] = Field(None, description="Human-readable model name")
    description: Optional[str] = Field(None, description="Model description")
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


class ModelRegistryResponse(BaseModel):
    """Full model registry entry response."""

    id: int
    model_type: str
    category: str
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
    request: CreateModelRequest, session: Session = Depends(get_db_sync)
) -> ModelRegistryResponse:
    """
    Create a new model in the registry.

    This allows adding new models dynamically without code changes.
    """
    try:
        # Check if model type already exists
        existing = (
            session.query(ModelRegistry)
            .filter(ModelRegistry.model_type == request.model_type)
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Model type '{request.model_type}' already exists",
            )

        # Create new model registry entry
        new_model = ModelRegistry(
            model_type=request.model_type,
            category=request.category,
            name=request.name,
            description=request.description,
            complexity=request.complexity,
            memory_usage=request.memory_usage,
            import_paths=request.import_paths,
            parameter_schema=request.parameter_schema,
            default_parameters=request.default_parameters,
            version=request.version,
            requires_special_handling=request.requires_special_handling,
            is_active=True,
        )

        session.add(new_model)
        session.commit()
        session.refresh(new_model)

        logger.info(f"Created new model: {request.model_type}")

        return ModelRegistryResponse(
            id=new_model.id,
            model_type=new_model.model_type,
            category=new_model.category,
            name=new_model.name,
            description=new_model.description,
            complexity=new_model.complexity,
            memory_usage=new_model.memory_usage,
            import_paths=new_model.import_paths,
            parameter_schema=new_model.parameter_schema,
            default_parameters=new_model.default_parameters,
            version=new_model.version,
            is_active=new_model.is_active,
            requires_special_handling=new_model.requires_special_handling,
            created_at=new_model.created_at.isoformat(),
            updated_at=new_model.updated_at.isoformat(),
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create model '{request.model_type}': {e}")
        raise HTTPException(status_code=500, detail="Failed to create model")


@router.put("/{model_type}", response_model=ModelRegistryResponse)
async def update_model(
    model_type: str,
    request: UpdateModelRequest,
    session: Session = Depends(get_db_sync),
) -> ModelRegistryResponse:
    """
    Update an existing model in the registry.

    Allows updating model metadata, parameters, or activation status.
    """
    try:
        model = (
            session.query(ModelRegistry)
            .filter(ModelRegistry.model_type == model_type)
            .first()
        )

        if not model:
            raise HTTPException(
                status_code=404, detail=f"Model '{model_type}' not found"
            )

        # Update fields that are provided
        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(model, field, value)

        session.commit()
        session.refresh(model)

        logger.info(f"Updated model: {model_type}")

        return ModelRegistryResponse(
            id=model.id,
            model_type=model.model_type,
            category=model.category,
            name=model.name,
            description=model.description,
            complexity=model.complexity,
            memory_usage=model.memory_usage,
            import_paths=model.import_paths,
            parameter_schema=model.parameter_schema,
            default_parameters=model.default_parameters,
            version=model.version,
            is_active=model.is_active,
            requires_special_handling=model.requires_special_handling,
            created_at=model.created_at.isoformat(),
            updated_at=model.updated_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to update model '{model_type}': {e}")
        raise HTTPException(status_code=500, detail="Failed to update model")


@router.delete("/{model_type}")
async def delete_model(
    model_type: str, session: Session = Depends(get_db_sync)
) -> Dict[str, str]:
    """
    Delete (deactivate) a model from the registry.

    Actually sets is_active=False rather than hard deleting to preserve history.
    """
    try:
        model = (
            session.query(ModelRegistry)
            .filter(ModelRegistry.model_type == model_type)
            .first()
        )

        if not model:
            raise HTTPException(
                status_code=404, detail=f"Model '{model_type}' not found"
            )

        # Soft delete - just deactivate
        model.is_active = False
        session.commit()

        logger.info(f"Deactivated model: {model_type}")

        return {"message": f"Model '{model_type}' deactivated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to deactivate model '{model_type}': {e}")
        raise HTTPException(status_code=500, detail="Failed to deactivate model")


@router.get("/", response_model=List[ModelRegistryResponse])
async def list_all_models(
    include_inactive: bool = False,
    category: Optional[str] = None,
    session: Session = Depends(get_db_sync),
) -> List[ModelRegistryResponse]:
    """
    List all models in registry, including inactive ones.

    Useful for admin interface showing complete model inventory.
    """
    try:
        query = session.query(ModelRegistry)

        if not include_inactive:
            query = query.filter(ModelRegistry.is_active)

        if category:
            query = query.filter(ModelRegistry.category == category)

        models = query.all()

        return [
            ModelRegistryResponse(
                id=m.id,
                model_type=m.model_type,
                category=m.category,
                name=m.name,
                description=m.description,
                complexity=m.complexity,
                memory_usage=m.memory_usage,
                import_paths=m.import_paths,
                parameter_schema=m.parameter_schema,
                default_parameters=m.default_parameters,
                version=m.version,
                is_active=m.is_active,
                requires_special_handling=m.requires_special_handling,
                created_at=m.created_at.isoformat(),
                updated_at=m.updated_at.isoformat(),
            )
            for m in models
        ]

    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve models")


@router.post("/{model_type}/test")
async def test_model_instantiation(
    model_type: str,
    test_parameters: Optional[Dict[str, Any]] = None,
    session: Session = Depends(get_db_sync),
) -> Dict[str, Any]:
    """
    Test that a model can be instantiated with given parameters.

    Useful for validating new model definitions before deployment.
    """
    try:
        # Import the TACTIC model registry service
        from ...models.registry import model_registry

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
