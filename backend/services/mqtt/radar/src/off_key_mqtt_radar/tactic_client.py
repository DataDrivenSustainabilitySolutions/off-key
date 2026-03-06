"""
TACTIC Model Registry Client for RADAR Service.

Replaces direct core package imports with HTTP calls to TACTIC middleware.
"""

import logging
import aiohttp
import asyncio
import time
import concurrent.futures
from typing import Dict, Any, List, Optional, Type

from .config.runtime import get_radar_tactic_client_settings

logger = logging.getLogger(__name__)


def _default_tactic_base_url() -> str:
    """Build TACTIC base URL from RADAR/container environment."""
    return get_radar_tactic_client_settings().base_url


def _default_cache_ttl_seconds() -> float:
    """Resolve model-registry cache TTL from environment."""
    return get_radar_tactic_client_settings().cache_ttl_seconds


class TacticModelError(Exception):
    """Custom exception for TACTIC model registry errors."""

    pass


class TacticModelClient:
    """Client for TACTIC model registry API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        cache_ttl_seconds: Optional[float] = None,
    ):
        self.base_url = (base_url or _default_tactic_base_url()).rstrip("/")
        self._model_cache: Dict[str, Dict[str, Any]] = {}
        self._preprocessor_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl_seconds = cache_ttl_seconds or _default_cache_ttl_seconds()
        self._model_cache_expires_at = 0.0
        self._preprocessor_cache_expires_at = 0.0

    def _is_cache_valid(self, expires_at: float) -> bool:
        return time.monotonic() < expires_at

    async def _refresh_model_cache(self, force: bool = False) -> None:
        """Refresh model registry cache when stale or explicitly forced."""
        if (
            self._model_cache
            and not force
            and self._is_cache_valid(self._model_cache_expires_at)
        ):
            return

        models = await self._make_request("GET", "/api/v1/models/")
        self._model_cache = {m["model_type"]: m for m in models}
        self._model_cache_expires_at = time.monotonic() + self._cache_ttl_seconds
        logger.info(
            "Cached %s models from TACTIC (ttl=%ss)",
            len(models),
            self._cache_ttl_seconds,
        )

    async def _refresh_preprocessor_cache(self, force: bool = False) -> None:
        """Refresh preprocessor registry cache when stale or explicitly forced."""
        if (
            self._preprocessor_cache
            and not force
            and self._is_cache_valid(self._preprocessor_cache_expires_at)
        ):
            return

        preprocessors = await self._make_request("GET", "/api/v1/models/preprocessors")
        self._preprocessor_cache = {p["model_type"]: p for p in preprocessors}
        self._preprocessor_cache_expires_at = time.monotonic() + self._cache_ttl_seconds
        logger.info(
            "Cached %s preprocessors from TACTIC (ttl=%ss)",
            len(preprocessors),
            self._cache_ttl_seconds,
        )

    @staticmethod
    def _run_coroutine_sync(coro: Any) -> Any:
        """
        Run a coroutine from sync code in both sync and async caller contexts.

        If called from within an active event loop, execute the coroutine in a
        worker thread with its own temporary loop.
        """
        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False

        if loop_running:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()

        return asyncio.run(coro)

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Make HTTP request to TACTIC."""
        url = f"{self.base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30.0, connect=10.0)

        try:
            # Use request-scoped sessions to avoid cross-event-loop session reuse.
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, **kwargs) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"TACTIC request failed: {response.status} - {error_text}"
                        )
                        raise TacticModelError(
                            f"TACTIC request failed: {response.status} - {error_text}"
                        )
        except aiohttp.ClientError as e:
            logger.error(f"TACTIC connection error: {e}")
            raise TacticModelError(f"TACTIC connection error: {e}")

    async def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available models."""
        await self._refresh_model_cache()
        return list(self._model_cache.values())

    async def get_available_preprocessors(self) -> List[Dict[str, Any]]:
        """Get list of available preprocessors."""
        await self._refresh_preprocessor_cache()
        return list(self._preprocessor_cache.values())

    async def validate_model_params(
        self, model_type: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Validate model parameters against schema."""
        request_data = {"model_type": model_type, "parameters": params or {}}

        response = await self._make_request(
            "POST", "/api/v1/models/validate", json=request_data
        )

        if not response.get("valid"):
            raise ValueError(response.get("error", "Validation failed"))

        return response["validated_parameters"]

    async def create_model_instance_validate(
        self, model_type: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Validate that model can be instantiated (doesn't return actual instance)."""
        request_data = {"model_type": model_type, "parameters": params or {}}

        return await self._make_request(
            "POST", "/api/v1/models/create-instance", json=request_data
        )

    # Synchronous wrapper methods for compatibility with existing code
    def validate_model_params_sync(
        self, model_type: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Synchronous wrapper for validate_model_params."""
        return self._run_coroutine_sync(self.validate_model_params(model_type, params))

    def validate_preprocessing_steps_sync(
        self, steps: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Synchronous validation for preprocessing steps."""
        if not steps:
            return []

        validated_steps = []
        for step in steps:
            step_type = step.get("type")
            params = step.get("params", {})

            # Use TACTIC to validate preprocessor parameters
            validated_params = self.validate_model_params_sync(step_type, params)
            validated_steps.append({"type": step_type, "params": validated_params})

        return validated_steps

    # Model instantiation methods (using importlib for actual model creation)
    def get_model_class(self, model_type: str) -> Type:
        """Get model class using cached model info and dynamic import."""
        return self._run_coroutine_sync(self._get_model_class_async(model_type))

    async def _get_model_class_async(self, model_type: str) -> Type:
        """Async version of get_model_class."""
        await self._refresh_model_cache()

        model_info = self._model_cache.get(model_type)
        if not model_info:
            await self._refresh_preprocessor_cache()
            model_info = self._preprocessor_cache.get(model_type)

        # Dynamic discovery: force one refresh round before declaring unknown.
        if not model_info:
            await self._refresh_model_cache(force=True)
            model_info = self._model_cache.get(model_type)
        if not model_info:
            await self._refresh_preprocessor_cache(force=True)
            model_info = self._preprocessor_cache.get(model_type)

        if not model_info:
            available_models = list(self._model_cache.keys())
            available_preprocessors = list(self._preprocessor_cache.keys())
            available = available_models + available_preprocessors
            raise ValueError(
                f"Unknown model type: '{model_type}'. Available: {available}"
            )

        # Extract import paths from cached model info (now includes import_paths)
        import_paths = model_info.get("import_paths", [])
        if not import_paths:
            raise ValueError(
                f"No import paths available for model type: '{model_type}'"
            )

        return self._import_model_class_dynamic(model_type, import_paths)

    def _import_model_class_dynamic(
        self, model_type: str, import_paths: List[str]
    ) -> Type:
        """Dynamically import model class using paths from TACTIC."""
        import importlib

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
            f"Failed to import model '{model_type}' from any known path: {error_msg}"
        )
        raise ImportError(f"Cannot import model '{model_type}'. Tried: {import_paths}")

    def get_preprocessor_class(self, step_type: str) -> Type:
        """Get preprocessor class."""
        return self.get_model_class(step_type)

    def create_model_instance(
        self, model_type: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Create model instance with validated parameters."""
        validated_params = self.validate_model_params_sync(model_type, params)

        # Special case: KNN requires similarity engine
        if model_type == "knn":
            return self._create_knn_model(validated_params)

        # Standard case: direct instantiation
        model_class = self.get_model_class(model_type)
        return model_class(**validated_params)

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


# Global client instance
_tactic_client = None


def get_tactic_client() -> TacticModelClient:
    """Get global TACTIC client instance."""
    global _tactic_client
    if _tactic_client is None:
        _tactic_client = TacticModelClient()
    return _tactic_client


# Compatibility functions for existing RADAR code
def validate_model_params(
    model_type: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Compatibility wrapper for core.models.validate_model_params."""
    client = get_tactic_client()
    return client.validate_model_params_sync(model_type, params)


def validate_preprocessing_steps(
    steps: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Compatibility wrapper for core.models.validate_preprocessing_steps."""
    client = get_tactic_client()
    return client.validate_preprocessing_steps_sync(steps)


def get_preprocessor_class(step_type: str) -> Type:
    """Compatibility wrapper for core.models.get_preprocessor_class."""
    client = get_tactic_client()
    return client.get_preprocessor_class(step_type)


def create_model_instance(
    model_type: str, params: Optional[Dict[str, Any]] = None
) -> Any:
    """Compatibility wrapper for core.models.create_model_instance."""
    client = get_tactic_client()
    return client.create_model_instance(model_type, params)
