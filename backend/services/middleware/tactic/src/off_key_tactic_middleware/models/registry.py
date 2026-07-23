"""
Database-backed Model Registry for TACTIC Middleware.

Replaces hardcoded MODEL_REGISTRY with dynamic database-backed registry
that allows runtime addition of new models without code changes.
"""

import asyncio
import importlib
import logging
from typing import Any

from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from off_key_core.db.base import get_engine
from off_key_core.db.models import ModelRegistry
from off_key_core.models import STATIC_MODEL_FAMILY, STATIC_MONITORING_STRATEGY
from sqlalchemy import and_, func, inspect, or_, text
from sqlalchemy.orm import Session

from .schemas import (
    PyODHBOSParams,
    PyODIsolationForestParams,
    PyODKNNParams,
    PyODLOFParams,
    PyODOCSVMParams,
    PyODPCAParams,
)

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
        """Populate static defaults and retire the removed dynamic catalog."""
        session.query(ModelRegistry).filter(
            or_(
                ModelRegistry.category != "model",
                ModelRegistry.family.is_(None),
                ModelRegistry.family != STATIC_MODEL_FAMILY,
            )
        ).update({ModelRegistry.is_active: False}, synchronize_session=False)

        default_models = [
            {
                "model_type": "pyod_iforest",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD Isolation Forest",
                "description": (
                    "Static Isolation Forest wrapped by conformal p-values"
                ),
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["pyod.models.iforest.IForest"],
                "parameter_schema": PyODIsolationForestParams.model_json_schema(),
                "default_parameters": PyODIsolationForestParams().model_dump(),
            },
            {
                "model_type": "pyod_knn",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD KNN",
                "description": "Static KNN detector wrapped by conformal p-values",
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["pyod.models.knn.KNN"],
                "parameter_schema": PyODKNNParams.model_json_schema(),
                "default_parameters": PyODKNNParams().model_dump(),
            },
            {
                "model_type": "pyod_lof",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD Local Outlier Factor",
                "description": "Static LOF detector wrapped by conformal p-values",
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["pyod.models.lof.LOF"],
                "parameter_schema": PyODLOFParams.model_json_schema(),
                "default_parameters": PyODLOFParams().model_dump(),
            },
            {
                "model_type": "pyod_ocsvm",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD One-Class SVM",
                "description": ("Static OCSVM detector wrapped by conformal p-values"),
                "complexity": "high",
                "memory_usage": "medium",
                "import_paths": ["pyod.models.ocsvm.OCSVM"],
                "parameter_schema": PyODOCSVMParams.model_json_schema(),
                "default_parameters": PyODOCSVMParams().model_dump(),
            },
            {
                "model_type": "pyod_hbos",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD HBOS",
                "description": "Static HBOS detector wrapped by conformal p-values",
                "complexity": "low",
                "memory_usage": "low",
                "import_paths": ["pyod.models.hbos.HBOS"],
                "parameter_schema": PyODHBOSParams.model_json_schema(),
                "default_parameters": PyODHBOSParams().model_dump(),
            },
            {
                "model_type": "pyod_pca",
                "category": "model",
                "family": STATIC_MODEL_FAMILY,
                "name": "PyOD PCA",
                "description": "Static PCA detector wrapped by conformal p-values",
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["pyod.models.pca.PCA"],
                "parameter_schema": PyODPCAParams.model_json_schema(),
                "default_parameters": PyODPCAParams().model_dump(),
            },
        ]

        for model_data in default_models:
            existing = (
                session.query(ModelRegistry)
                .filter(ModelRegistry.model_type == model_data["model_type"])
                .first()
            )
            if existing:
                for key, value in model_data.items():
                    setattr(existing, key, value)
                existing.is_active = True
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
                        ModelRegistry.family == STATIC_MODEL_FAMILY,
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
                }
                for m in models
            ]

    def get_model_class(self, model_type: str) -> type:
        """Dynamically import and return the model class."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type)

            if not model:
                available = [
                    m.model_type
                    for m in session.query(ModelRegistry.model_type)
                    .filter(ModelRegistry.is_active)
                    .all()
                ]
                raise ValueError(
                    f"Unknown model type: '{model_type}'. Available: {available}"
                )

            return self._import_model_class(model_type, model.import_paths)

    def validate_model_params(
        self,
        model_type: str,
        params: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Validate and normalize model parameters using DB-backed schema."""
        self._ensure_ready()
        params = params or {}
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type, category)
            if not model:
                raise ValueError(
                    self._format_missing_model_message(model_type, category)
                )

            return self._validate_params_with_schema(model, params)

    @staticmethod
    def _import_class(import_path: str) -> type:
        module_path, class_name = import_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def create_model_instance(
        self, model_type: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Reject in-process execution; RADAR owns all static model instances."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type, category="model")
            if not model:
                raise ValueError(
                    self._format_missing_model_message(model_type, "model")
                )
            self._validate_params_with_schema(model, params or {})
            raise ValueError(
                f"Model '{model_type}' is instantiated by the RADAR runtime. "
                "TACTIC validates its registry schema only."
            )

    def validate_model_instantiation(
        self, model_type: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate static parameters without instantiating RADAR-owned models."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type, category="model")
            if not model:
                raise ValueError(
                    self._format_missing_model_message(model_type, "model")
                )

            validated_params = self._validate_params_with_schema(model, params or {})
            return {
                "validated_parameters": validated_params,
                "instantiated": False,
                "runtime_owner": "radar",
            }

    @staticmethod
    def _format_missing_model_message(model_type: str, category: str | None) -> str:
        if category == "model":
            return f"Unknown model type: '{model_type}'"
        return f"Unknown model type: '{model_type}'"

    @staticmethod
    def _strategy_for_model(model: ModelRegistry) -> str:
        return STATIC_MONITORING_STRATEGY

    @staticmethod
    def _get_active_entry(
        session: Session, model_type: str, category: str | None = None
    ) -> ModelRegistry | None:
        query = session.query(ModelRegistry).filter(
            ModelRegistry.model_type == model_type,
            ModelRegistry.is_active,
            ModelRegistry.category == "model",
            ModelRegistry.family == STATIC_MODEL_FAMILY,
        )
        if category:
            query = query.filter(ModelRegistry.category == category)
        return query.first()

    @staticmethod
    def _import_model_class(model_type: str, import_paths: list[str]) -> type:
        errors = []
        for import_path in import_paths:
            try:
                return ModelRegistryService._import_class(import_path)
            except (ImportError, AttributeError, ModuleNotFoundError) as e:
                errors.append(f"{import_path}: {e}")
                continue

        error_msg = "; ".join(errors) if errors else "unknown"
        logger.error(
            "Failed to import model '%s' from any known path: %s",
            model_type,
            error_msg,
        )
        raise ImportError(f"Cannot import model '{model_type}'. Tried: {import_paths}")

    @staticmethod
    def _validate_params_with_schema(
        model: ModelRegistry, params: dict[str, Any]
    ) -> dict[str, Any]:
        defaults = model.default_parameters or {}
        merged = {**defaults, **params}

        schema = model.parameter_schema or {}
        if not schema:
            raise ValueError(
                f"No parameter schema available for model '{model.model_type}'"
            )

        try:
            jsonschema_validate(instance=merged, schema=schema)
        except JsonSchemaValidationError as exc:
            path = ".".join(str(p) for p in exc.path) if exc.path else ""
            message = f"{path}: {exc.message}" if path else exc.message
            raise ValueError(
                f"Invalid parameters for model '{model.model_type}': {message}"
            ) from exc

        return merged
