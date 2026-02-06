"""
Database-backed Model Registry for TACTIC Middleware.

Replaces hardcoded MODEL_REGISTRY with dynamic database-backed registry
that allows runtime addition of new models without code changes.
"""

import asyncio
import importlib
import logging
from typing import Any, Dict, Type, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, inspect, text, or_, func
from jsonschema import validate as jsonschema_validate
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from off_key_core.db.models import ModelRegistry
from off_key_core.db.base import get_engine

from .schemas import (
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    MondrianIsolationForestParams,
    StandardScalerParams,
    IncrementalPCAParams,
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
        last_error: Optional[Exception] = None

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
        """Populate database registry with default models if empty."""
        count = session.query(ModelRegistry).count()
        if count == 0:
            logger.info("Model registry empty, populating with defaults...")
            self._populate_default_models(session)

    def _ensure_ready(self) -> None:
        if not self._initialized:
            raise ModelRegistryNotReadyError(
                "Model registry not initialized yet. "
                "Try again once startup initialization completes."
            )

    def _populate_default_models(self, session: Session):
        """Populate default model definitions."""
        default_models = [
            # Distance-based Models
            {
                "model_type": "knn",
                "category": "model",
                "family": "distance",
                "name": "Incremental K-Nearest Neighbors",
                "description": (
                    "Incremental K-Nearest Neighbors for streaming anomaly detection"
                ),
                "complexity": "low",
                "memory_usage": "medium",
                "import_paths": ["onad.model.distance.knn.KNN"],
                "parameter_schema": IncrementalKNNParams.model_json_schema(),
                "default_parameters": IncrementalKNNParams().model_dump(),
                "requires_special_handling": True,  # KNN needs similarity engine
            },
            # Forest-based Models
            {
                "model_type": "isolation_forest",
                "category": "model",
                "family": "forest",
                "name": "Online Isolation Forest",
                "description": (
                    "Online Isolation Forest for streaming anomaly detection"
                ),
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["onad.model.iforest.online.OnlineIsolationForest"],
                "parameter_schema": OnlineIsolationForestParams.model_json_schema(),
                "default_parameters": OnlineIsolationForestParams().model_dump(),
            },
            {
                "model_type": "mondrian_forest",
                "category": "model",
                "family": "forest",
                "name": "Mondrian Forest",
                "description": "Mondrian Forest - fast streaming anomaly detection",
                "complexity": "low",
                "memory_usage": "low",
                "import_paths": ["onad.model.iforest.mondrian.MondrianForest"],
                "parameter_schema": MondrianIsolationForestParams.model_json_schema(),
                "default_parameters": MondrianIsolationForestParams().model_dump(),
            },
            # SVM-based Models
            {
                "model_type": "adaptive_svm",
                "category": "model",
                "family": "svm",
                "name": "Adaptive One-Class SVM",
                "description": "Adaptive One-Class SVM with incremental kernel updates",
                "complexity": "high",
                "memory_usage": "high",
                "import_paths": [
                    "onad.model.svm.adaptive.IncrementalOneClassSVMAdaptiveKernel"
                ],
                "parameter_schema": AdaptiveSVMParams.model_json_schema(),
                "default_parameters": AdaptiveSVMParams().model_dump(),
            },
            # Preprocessors
            {
                "model_type": "standard_scaler",
                "category": "preprocessor",
                "family": "scaling",
                "name": "Standard Scaler",
                "description": (
                    "Standardize features by removing mean and scaling to unit variance"
                ),
                "complexity": "low",
                "memory_usage": "low",
                "import_paths": ["onad.transform.preprocessing.scaler.StandardScaler"],
                "parameter_schema": StandardScalerParams.model_json_schema(),
                "default_parameters": StandardScalerParams().model_dump(),
            },
            {
                "model_type": "pca",
                "category": "preprocessor",
                "family": "projection",
                "name": "Incremental PCA",
                "description": (
                    "Incremental PCA for dimensionality reduction on streams"
                ),
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": [
                    "onad.transform.projection.incremental_pca.IncrementalPCA"
                ],
                "parameter_schema": IncrementalPCAParams.model_json_schema(),
                "default_parameters": IncrementalPCAParams().model_dump(),
            },
        ]

        for model_data in default_models:
            model = ModelRegistry(**model_data)
            session.add(model)

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get all available models from database."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            models = (
                session.query(ModelRegistry)
                .filter(
                    and_(
                        ModelRegistry.is_active,
                        ModelRegistry.category == "model",
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
                }
                for m in models
            ]

    def get_available_preprocessors(self) -> List[Dict[str, Any]]:
        """Get all available preprocessors from database."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            preprocessors = (
                session.query(ModelRegistry)
                .filter(
                    and_(
                        ModelRegistry.is_active,
                        ModelRegistry.category == "preprocessor",
                    )
                )
                .all()
            )

            return [
                {
                    "model_type": p.model_type,
                    "family": p.family,
                    "name": p.name,
                    "description": p.description,
                    "import_paths": p.import_paths,
                    "parameter_schema": p.parameter_schema,
                    "default_parameters": p.default_parameters,
                    "version": p.version,
                    "requires_special_handling": p.requires_special_handling,
                }
                for p in preprocessors
            ]

    def get_model_class(self, model_type: str) -> Type:
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
        params: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
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

    def validate_preprocessing_steps(
        self, steps: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Validate and normalize preprocessing steps against registry."""
        self._ensure_ready()
        if not steps:
            return []

        validated_steps = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError("Each preprocessing step must be an object")

            step_type = step.get("type")
            if not step_type:
                raise ValueError("Each preprocessing step must include a 'type' field")

            params = step.get("params") or {}
            validated_params = self.validate_model_params(
                step_type, params, category="preprocessor"
            )
            validated_steps.append({"type": step_type, "params": validated_params})

        return validated_steps

    def _create_knn_model(self, validated_params: Dict[str, Any]) -> Any:
        """Create KNN model with FaissSimilaritySearchEngine."""
        try:
            from onad.utils.similar.faiss_engine import FaissSimilaritySearchEngine
            from onad.model.distance.knn import KNN
        except ImportError as e:
            logger.error(f"Failed to import KNN dependencies: {e}")
            raise ImportError(
                "Cannot import KNN model. Ensure onad is installed with FAISS support."
            ) from e

        params = validated_params.copy()
        window_size = params.pop("window_size", 1000)
        warm_up = params.pop("warm_up", 50)
        k = params.get("k", 5)

        similarity_engine = FaissSimilaritySearchEngine(
            window_size=window_size,
            warm_up=warm_up,
        )

        return KNN(k=k, similarity_engine=similarity_engine)

    def create_model_instance(
        self, model_type: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Create a model instance with validated parameters."""
        self._ensure_ready()
        with Session(get_engine()) as session:
            model = self._get_active_entry(session, model_type, category="model")
            if not model:
                raise ValueError(
                    self._format_missing_model_message(model_type, "model")
                )

            validated_params = self._validate_params_with_schema(model, params or {})

            if model.requires_special_handling:
                if model_type == "knn":
                    return self._create_knn_model(validated_params)
                raise ValueError(
                    f"Model '{model_type}' requires special handling but no handler "
                    "is registered."
                )

            model_class = self._import_model_class(model_type, model.import_paths)
            return model_class(**validated_params)

    @staticmethod
    def _format_missing_model_message(model_type: str, category: Optional[str]) -> str:
        if category == "preprocessor":
            return f"Unknown preprocessor type: '{model_type}'"
        if category == "model":
            return f"Unknown model type: '{model_type}'"
        return f"Unknown model type: '{model_type}'"

    @staticmethod
    def _get_active_entry(
        session: Session, model_type: str, category: Optional[str] = None
    ) -> Optional[ModelRegistry]:
        query = session.query(ModelRegistry).filter(
            ModelRegistry.model_type == model_type,
            ModelRegistry.is_active,
        )
        if category:
            query = query.filter(ModelRegistry.category == category)
        return query.first()

    @staticmethod
    def _import_model_class(model_type: str, import_paths: List[str]) -> Type:
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
            "Failed to import model '%s' from any known path: %s",
            model_type,
            error_msg,
        )
        raise ImportError(f"Cannot import model '{model_type}'. Tried: {import_paths}")

    @staticmethod
    def _validate_params_with_schema(
        model: ModelRegistry, params: Dict[str, Any]
    ) -> Dict[str, Any]:
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
