"""
Database-backed Model Registry for TACTIC Middleware.

Replaces hardcoded MODEL_REGISTRY with dynamic database-backed registry
that allows runtime addition of new models without code changes.
"""

import importlib
import logging
from typing import Any, Dict, Type, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_

from off_key_core.db.models import ModelRegistry
from off_key_core.config.config import settings
from off_key_core.db.base import get_engine

from .schemas import (
    ModelHyperparameters,
    IncrementalKNNParams,
    OnlineIsolationForestParams,
    AdaptiveSVMParams,
    MondrianIsolationForestParams,
    StandardScalerParams,
    IncrementalPCAParams,
)

logger = logging.getLogger(__name__)


class ModelRegistryService:
    """Database-backed model registry service."""

    def __init__(self):
        self._schema_map = {
            "knn": IncrementalKNNParams,
            "isolation_forest": OnlineIsolationForestParams,
            "mondrian_forest": MondrianIsolationForestParams,
            "adaptive_svm": AdaptiveSVMParams,
            "standard_scaler": StandardScalerParams,
            "pca": IncrementalPCAParams,
        }
        # Initialize registry if empty
        self._ensure_registry_populated()

    def _ensure_registry_populated(self):
        """Populate database registry with default models if empty."""
        with Session(get_engine()) as session:
            count = session.query(ModelRegistry).count()
            if count == 0:
                logger.info("Model registry empty, populating with defaults...")
                self._populate_default_models(session)
                session.commit()

    def _populate_default_models(self, session: Session):
        """Populate default model definitions."""
        default_models = [
            # Distance-based Models
            {
                "model_type": "knn",
                "category": "model",
                "name": "Incremental K-Nearest Neighbors",
                "description": "Incremental K-Nearest Neighbors for streaming anomaly detection",
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
                "name": "Online Isolation Forest",
                "description": "Online Isolation Forest for streaming anomaly detection",
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["onad.model.iforest.online.OnlineIsolationForest"],
                "parameter_schema": OnlineIsolationForestParams.model_json_schema(),
                "default_parameters": OnlineIsolationForestParams().model_dump(),
            },
            {
                "model_type": "mondrian_forest",
                "category": "model",
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
                "name": "Adaptive One-Class SVM",
                "description": "Adaptive One-Class SVM with incremental kernel updates",
                "complexity": "high",
                "memory_usage": "high",
                "import_paths": ["onad.model.svm.adaptive.IncrementalOneClassSVMAdaptiveKernel"],
                "parameter_schema": AdaptiveSVMParams.model_json_schema(),
                "default_parameters": AdaptiveSVMParams().model_dump(),
            },
            # Preprocessors
            {
                "model_type": "standard_scaler",
                "category": "preprocessor",
                "name": "Standard Scaler",
                "description": "Standardize features by removing mean and scaling to unit variance",
                "complexity": "low",
                "memory_usage": "low",
                "import_paths": ["onad.transform.preprocessing.scaler.StandardScaler"],
                "parameter_schema": StandardScalerParams.model_json_schema(),
                "default_parameters": StandardScalerParams().model_dump(),
            },
            {
                "model_type": "pca",
                "category": "preprocessor",
                "name": "Incremental PCA",
                "description": "Incremental PCA for dimensionality reduction on streams",
                "complexity": "medium",
                "memory_usage": "medium",
                "import_paths": ["onad.transform.projection.incremental_pca.IncrementalPCA"],
                "parameter_schema": IncrementalPCAParams.model_json_schema(),
                "default_parameters": IncrementalPCAParams().model_dump(),
            },
        ]

        for model_data in default_models:
            model = ModelRegistry(**model_data)
            session.add(model)

    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get all available models from database."""
        with Session(get_engine()) as session:
            models = session.query(ModelRegistry).filter(
                and_(ModelRegistry.is_active == True, ModelRegistry.category == "model")
            ).all()

            return [{
                "model_type": m.model_type,
                "name": m.name,
                "description": m.description,
                "complexity": m.complexity,
                "memory_usage": m.memory_usage,
                "import_paths": m.import_paths,
                "parameter_schema": m.parameter_schema,
                "default_parameters": m.default_parameters,
                "version": m.version,
                "requires_special_handling": m.requires_special_handling,
            } for m in models]

    def get_available_preprocessors(self) -> List[Dict[str, Any]]:
        """Get all available preprocessors from database."""
        with Session(get_engine()) as session:
            preprocessors = session.query(ModelRegistry).filter(
                and_(ModelRegistry.is_active == True, ModelRegistry.category == "preprocessor")
            ).all()

            return [{
                "model_type": p.model_type,
                "name": p.name,
                "description": p.description,
                "import_paths": p.import_paths,
                "parameter_schema": p.parameter_schema,
                "default_parameters": p.default_parameters,
                "version": p.version,
                "requires_special_handling": p.requires_special_handling,
            } for p in preprocessors]

    def get_model_class(self, model_type: str) -> Type:
        """Dynamically import and return the model class."""
        with Session(get_engine()) as session:
            model = session.query(ModelRegistry).filter(
                and_(
                    ModelRegistry.model_type == model_type,
                    ModelRegistry.is_active == True
                )
            ).first()

            if not model:
                available = [m.model_type for m in session.query(ModelRegistry.model_type).filter(ModelRegistry.is_active == True).all()]
                raise ValueError(f"Unknown model type: '{model_type}'. Available: {available}")

            errors = []
            for import_path in model.import_paths:
                try:
                    module_path, class_name = import_path.rsplit(".", 1)
                    module = importlib.import_module(module_path)
                    model_class = getattr(module, class_name)
                    return model_class
                except (ImportError, AttributeError, ModuleNotFoundError) as e:
                    errors.append(f"{import_path}: {e}")
                    continue

            error_msg = "; ".join(errors) if errors else "unknown"
            logger.error(f"Failed to import model '{model_type}' from any known path: {error_msg}")
            raise ImportError(f"Cannot import model '{model_type}'. Tried: {model.import_paths}")

    def validate_model_params(self, model_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Validate and normalize model parameters."""
        schema_class = self._schema_map.get(model_type)
        if not schema_class:
            raise ValueError(f"No schema available for model type: '{model_type}'")

        params = params or {}
        try:
            validated = schema_class(**params)
            return validated.model_dump(mode="json")
        except Exception as e:
            raise ValueError(f"Invalid parameters for model '{model_type}': {e}") from e

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

    def create_model_instance(self, model_type: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Create a model instance with validated parameters."""
        validated_params = self.validate_model_params(model_type, params)

        # Check if special handling is required
        with Session(get_engine()) as session:
            model = session.query(ModelRegistry).filter(
                and_(
                    ModelRegistry.model_type == model_type,
                    ModelRegistry.is_active == True
                )
            ).first()

            if model and model.requires_special_handling and model_type == "knn":
                return self._create_knn_model(validated_params)

        # Standard case: direct instantiation
        model_class = self.get_model_class(model_type)
        return model_class(**validated_params)


# Global registry service instance
model_registry = ModelRegistryService()