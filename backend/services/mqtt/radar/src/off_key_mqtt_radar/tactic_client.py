"""
TACTIC Model Registry Client for RADAR Service.

Replaces direct core package imports with HTTP calls to TACTIC middleware.
"""

import asyncio
import concurrent.futures
import logging
import time
from typing import Any

import aiohttp

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


class TacticModelClient:
    """Client for TACTIC model registry API."""

    def __init__(
        self,
        base_url: str | None = None,
        cache_ttl_seconds: float | None = None,
    ):
        self.base_url = (base_url or _default_tactic_base_url()).rstrip("/")
        self._model_cache: dict[str, dict[str, Any]] = {}
        self._cache_ttl_seconds = cache_ttl_seconds or _default_cache_ttl_seconds()
        self._model_cache_expires_at = 0.0

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
            "event=radar.tactic_models_cached count=%s ttl_s=%s",
            len(models),
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
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.request(method, url, **kwargs) as response,
            ):
                if response.status == 200:
                    return await response.json()
                error_text = await response.text()
                logger.error(
                    "event=radar.tactic_request_failed status=%s error=%s",
                    response.status,
                    error_text,
                )
                raise TacticModelError(
                    f"TACTIC request failed: {response.status} - {error_text}"
                )
        except aiohttp.ClientError as e:
            logger.error(
                "event=radar.tactic_connection_error error=%s",
                str(e),
                exc_info=True,
            )
            raise TacticModelError(f"TACTIC connection error: {e}")

    async def get_available_models(self) -> list[dict[str, Any]]:
        """Get list of available models."""
        await self._refresh_model_cache()
        return list(self._model_cache.values())

    async def validate_model_params(
        self, model_type: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate model parameters against schema."""
        request_data = {"model_type": model_type, "parameters": params or {}}

        response = await self._make_request(
            "POST", "/api/v1/models/validate", json=request_data
        )

        if not response.get("valid"):
            raise ValueError(response.get("error", "Validation failed"))

        return response["validated_parameters"]

    # Synchronous wrapper methods for compatibility with existing code
    def validate_model_params_sync(
        self, model_type: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Synchronous wrapper for validate_model_params."""
        return self._run_coroutine_sync(self.validate_model_params(model_type, params))


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
    model_type: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compatibility wrapper for core.models.validate_model_params."""
    client = get_tactic_client()
    return client.validate_model_params_sync(model_type, params)
