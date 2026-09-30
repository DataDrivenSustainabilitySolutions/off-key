"""Use-case service for model-registry admin endpoints."""

from typing import Any

from off_key_core.config.logs import logger
from off_key_core.db.models import ModelRegistry
from off_key_core.models import ADAPTIVE_MODELS_BY_TYPE, validate_adaptive_model_params
from off_key_core.models.static import STATIC_MODELS, validate_static_model_params

from ..domain import InfrastructureError, NotFoundError, ValidationError
from ..repositories import ModelRegistryAdminRepository


class ModelRegistryAdminService:
    """Application service for model-registry admin operations."""

    def __init__(self, repository: ModelRegistryAdminRepository):
        self._repository = repository

    def update_model(
        self,
        *,
        model_type: str,
        update_data: dict[str, Any],
    ) -> dict[str, Any]:
        model = self._repository.get_by_model_type(model_type=model_type)
        if model is None:
            raise NotFoundError(f"Model '{model_type}' not found")

        if model_type not in STATIC_MODELS and model_type not in ADAPTIVE_MODELS_BY_TYPE:
            raise ValidationError(f"Model '{model_type}' is not shipped in the RADAR runtime")
        if "default_parameters" in update_data:
            validate = (
                validate_static_model_params if model_type in STATIC_MODELS
                else validate_adaptive_model_params
            )
            try:
                update_data = {**update_data, "default_parameters": validate(
                    model_type, update_data["default_parameters"],
                )}
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        for field, value in update_data.items():
            setattr(model, field, value)

        try:
            self._repository.commit()
            self._repository.refresh(model)
            logger.info(f"Updated model: {model_type}")
        except Exception as exc:
            self._repository.rollback()
            raise InfrastructureError(f"Failed to update model: {exc}") from exc

        return self._to_response(model)

    def deactivate_model(self, *, model_type: str) -> dict[str, str]:
        model = self._repository.get_by_model_type(model_type=model_type)
        if model is None:
            raise NotFoundError(f"Model '{model_type}' not found")

        model.is_active = False
        try:
            self._repository.commit()
            logger.info(f"Deactivated model: {model_type}")
        except Exception as exc:
            self._repository.rollback()
            raise InfrastructureError(f"Failed to deactivate model: {exc}") from exc

        return {"message": f"Model '{model_type}' deactivated successfully"}

    def list_models(
        self,
        *,
        include_inactive: bool,
        category: str | None,
    ) -> list[dict[str, Any]]:
        try:
            models = self._repository.list_models(
                include_inactive=include_inactive,
                category=category,
            )
        except Exception as exc:
            raise InfrastructureError(f"Failed to list models: {exc}") from exc
        return [self._to_response(model) for model in models]

    @staticmethod
    def _to_response(model: ModelRegistry) -> dict[str, Any]:
        return {
            "id": model.id,
            "model_type": model.model_type,
            "category": model.category,
            "family": model.family,
            "name": model.name,
            "description": model.description,
            "complexity": model.complexity,
            "memory_usage": model.memory_usage,
            "import_paths": model.import_paths,
            "parameter_schema": model.parameter_schema,
            "default_parameters": model.default_parameters,
            "version": model.version,
            "is_active": model.is_active,
            "requires_special_handling": model.requires_special_handling,
            "created_at": (
                model.created_at.isoformat() if model.created_at is not None else ""
            ),
            "updated_at": (
                model.updated_at.isoformat() if model.updated_at is not None else ""
            ),
        }
