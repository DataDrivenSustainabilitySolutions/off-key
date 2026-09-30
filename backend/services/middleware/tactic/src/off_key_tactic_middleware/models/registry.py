"""
Database-backed Model Registry for TACTIC Middleware.

Stores metadata, defaults, and activation for the detectors shipped in RADAR.
"""

import asyncio
import logging
from typing import Any

from off_key_core.db.base import get_engine
from off_key_core.db.models import ModelRegistry
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
from sqlalchemy import and_, func, inspect, or_, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ModelRegistryNotReadyError(RuntimeError):
    """Raised when registry storage is unavailable or not initialized."""


class ModelRegistryService:
    """Database-backed model registry service."""

    def __init__(self):
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    async def initialize(
        self,
        max_retries: int = 30,
        retry_interval_seconds: float = 2.0,
    ) -> None:
        """
        Initialize registry storage and seed defaults.

        Runs at service startup. This avoids DB access at import time and makes
        startup behavior explicit and retryable.
        """
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                self._initialize_once()
                self._initialized = True
                logger.info("Model registry initialized successfully")
                return
            except Exception as exc:
                last_error = exc
                self._initialized = False

                if attempt < max_retries:
                    logger.warning(
                        "Model registry initialization attempt %s/%s failed: %s. "
                        "Retrying in %.1fs",
                        attempt,
                        max_retries,
                        exc,
                        retry_interval_seconds,
                    )
                    await asyncio.sleep(retry_interval_seconds)
                else:
                    break

        raise ModelRegistryNotReadyError(
            "Model registry initialization failed after "
            f"{max_retries} attempts. Verify DB connectivity and schema readiness."
        ) from last_error

    def _initialize_once(self) -> None:
        engine = get_engine()
        inspector = inspect(engine)

        with Session(engine) as session:
            session.execute(text("SELECT 1"))

            if not inspector.has_table(ModelRegistry.__tablename__):
                raise ModelRegistryNotReadyError(
                    "Required table 'model_registry' not found. "
                    "Run DB schema initialization/migrations before starting TACTIC."
                )
            columns = {
                column["name"]
                for column in inspector.get_columns(ModelRegistry.__tablename__)
            }
            if "family" not in columns:
                raise ModelRegistryNotReadyError(
                    "Required column 'model_registry.family' not found. "
                    "Run DB schema initialization/migrations before starting TACTIC."
                )
            missing_family_entries = (
                session.query(ModelRegistry.model_type)
                .filter(
                    ModelRegistry.is_active,
                    or_(
                        ModelRegistry.family.is_(None),
                        func.trim(ModelRegistry.family) == "",
                    ),
                )
                .all()
            )
            if missing_family_entries:
                missing_types = ", ".join(
                    model_type for (model_type,) in missing_family_entries[:20]
                )
                raise ModelRegistryNotReadyError(
                    "Some active model_registry entries have empty family values. "
                    f"Fix these model types and retry: {missing_types}"
                )

            self._ensure_registry_populated(session)
            session.commit()

    def _ensure_registry_populated(self, session: Session) -> None:
        """Populate or update built-in registry entries idempotently."""
        self._populate_default_models(session)

    def _ensure_ready(self) -> None:
        if not self._initialized:
            raise ModelRegistryNotReadyError(
                "Model registry not initialized yet. "
                "Try again once startup initialization completes."
            )

    def _populate_default_models(self, session: Session):
        """Populate the immutable static and adaptive runtime catalogs."""
        session.query(ModelRegistry).filter(
            or_(
                ModelRegistry.category != "model",
                ModelRegistry.family.is_(None),
                ModelRegistry.family.notin_(
                    [STATIC_MODEL_FAMILY, ADAPTIVE_MODEL_FAMILY]
                ),
            )
        ).update({ModelRegistry.is_active: False}, synchronize_session=False)

        default_models = [
            {
                "model_type": model_type,
                "category": "model",
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
            }
            for model_type, definition in STATIC_MODELS.items()
        ]
        session.query(ModelRegistry).filter(
            ModelRegistry.family == STATIC_MODEL_FAMILY,
            ModelRegistry.model_type.notin_(STATIC_MODELS),
        ).update({ModelRegistry.is_active: False}, synchronize_session=False)

        session.query(ModelRegistry).filter(
            ModelRegistry.family == ADAPTIVE_MODEL_FAMILY,
            ModelRegistry.model_type.notin_(ADAPTIVE_MODELS_BY_TYPE),
        ).update({ModelRegistry.is_active: False}, synchronize_session=False)
        default_models.extend(
            {
                "model_type": model_type,
                "category": "model",
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
            }
            for model_type, definition in ADAPTIVE_MODELS_BY_TYPE.items()
        )

        for model_data in default_models:
            existing = (
                session.query(ModelRegistry)
                .filter(ModelRegistry.model_type == model_data["model_type"])
                .first()
            )
            if existing:
                for key in (
                    "category",
                    "family",
                    "import_paths",
                    "parameter_schema",
                    "version",
                    "requires_special_handling",
                ):
                    setattr(existing, key, model_data[key])
                self._validate_params_with_schema(existing, {})
            else:
                session.add(ModelRegistry(**model_data))

    def get_available_models(self) -> list[dict[str, Any]]:
        """Get all available models from database."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            models = (
                session.query(ModelRegistry)
                .filter(
                    and_(
                        ModelRegistry.is_active,
                        ModelRegistry.category == "model",
                        ModelRegistry.model_type.in_(
                            [*STATIC_MODELS, *ADAPTIVE_MODELS_BY_TYPE]
                        ),
                        ModelRegistry.family.in_(
                            [STATIC_MODEL_FAMILY, ADAPTIVE_MODEL_FAMILY]
                        ),
                    )
                )
                .all()
            )

            return [
                {
                    "model_type": m.model_type,
                    "family": m.family,
                    "name": m.name,
                    "description": m.description,
                    "complexity": m.complexity,
                    "memory_usage": m.memory_usage,
                    "import_paths": m.import_paths,
                    "parameter_schema": m.parameter_schema,
                    "default_parameters": m.default_parameters,
                    "version": m.version,
                    "requires_special_handling": m.requires_special_handling,
                    "strategy": self._strategy_for_model(m),
                    **adaptive_model_metadata(m.model_type),
                }
                for m in models
            ]

    def validate_model_params(
        self,
        model_type: str,
        params: dict[str, Any] | None = None,
        category: str | None = None,
        family: str | None = None,
    ) -> dict[str, Any]:
        """Validate and normalize model parameters using DB-backed schema."""
        self._ensure_ready()
        params = params or {}
        with Session(get_engine()) as session:
            model = self._get_active_entry(
                session, model_type, category=category, family=family
            )
            if not model:
                raise ValueError(f"Unknown model type: '{model_type}'")

            return self._validate_params_with_schema(model, params)

    def validate_model_instantiation(
        self, model_type: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate static parameters without instantiating RADAR-owned models."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type, category="model")
            if not model:
                raise ValueError(f"Unknown model type: '{model_type}'")

            validated_params = self._validate_params_with_schema(model, params or {})
            return {
                "validated_parameters": validated_params,
                "instantiated": False,
                "runtime_owner": "radar",
            }

    @staticmethod
    def _strategy_for_model(model: ModelRegistry) -> str:
        if model.family == ADAPTIVE_MODEL_FAMILY:
            return ADAPTIVE_MONITORING_STRATEGY
        return STATIC_MONITORING_STRATEGY

    @staticmethod
    def _get_active_entry(
        session: Session,
        model_type: str,
        category: str | None = None,
        family: str | None = None,
    ) -> ModelRegistry | None:
        if (
            model_type not in STATIC_MODELS
            and model_type not in ADAPTIVE_MODELS_BY_TYPE
        ):
            raise ValueError(
                f"Model '{model_type}' is not shipped in the RADAR runtime"
            )
        query = session.query(ModelRegistry).filter(
            ModelRegistry.model_type == model_type,
            ModelRegistry.is_active,
            ModelRegistry.category == "model",
        )
        if family is not None:
            if family not in {STATIC_MODEL_FAMILY, ADAPTIVE_MODEL_FAMILY}:
                raise ValueError(f"Unsupported executable model family: {family}")
            query = query.filter(ModelRegistry.family == family)
        else:
            query = query.filter(
                ModelRegistry.family.in_([STATIC_MODEL_FAMILY, ADAPTIVE_MODEL_FAMILY])
            )
        if category:
            query = query.filter(ModelRegistry.category == category)
        return query.first()

    @staticmethod
    def _validate_params_with_schema(
        model: ModelRegistry, params: dict[str, Any]
    ) -> dict[str, Any]:
        merged = {**(model.default_parameters or {}), **params}
        if model.family == ADAPTIVE_MODEL_FAMILY:
            return validate_adaptive_model_params(model.model_type, merged)
        return validate_static_model_params(model.model_type, merged)
