"""
HTTP client for communicating with the TACTIC middleware service.
"""

import asyncio
import json
from functools import cached_property
from typing import Any
from urllib.parse import quote

import aiohttp
from off_key_core.config.logs import correlation_headers, logger
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.schemas.favorites import FavoriteRef
from off_key_core.schemas.radar import MonitorSetup

from off_key_api_gateway.settings import get_service_endpoints_settings


class TacticError(Exception):
    """Typed error for TACTIC HTTP failures."""

    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def path_segment(value: str) -> str:
    if value in {"", ".", ".."} or "/" in value or "\\" in value:
        raise TacticError("Invalid resource identifier", status=422)
    return quote(value, safe="")


class Tactic:
    """
    Async HTTP client for communicating with TACTIC middleware service.
    """

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._max_retries = 2

    # Settings are read on first use so importing the gateway needs no environment.
    @cached_property
    def base_url(self) -> str:
        base_url = get_service_endpoints_settings().tactic_service_base_url
        logger.info(f"Tactic facade initialized with base URL: {base_url}")
        return base_url

    @cached_property
    def timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(
            total=get_service_endpoints_settings().TACTIC_SERVICE_REQUEST_TIMEOUT_SECONDS
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Create or reuse a shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the shared session if it exists."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | None = None,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> Any:
        """
        Make an HTTP request to the TACTIC service.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint path
            json_data: JSON payload for POST requests
            params: Query parameters
            content: Raw request body, sent instead of JSON (an upload)
            content_type: Media type of ``content``

        Returns:
            Dict: Response JSON data

        Raises:
            Exception: If the request fails
        """
        url = f"{self.base_url}{endpoint}"
        normalized_params = self._normalize_query_params(params)

        attempt = 0
        while True:
            attempt += 1
            try:
                session = await self._get_session()
                async with session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    data=content,
                    params=normalized_params,
                    headers={
                        **correlation_headers(),
                        **(headers or {}),
                        **({"Content-Type": content_type} if content_type else {}),
                        "X-Off-Key-Service-Key": (
                            get_service_auth_settings().INTERNAL_API_SECRET.get_secret_value()
                        ),
                    },
                ) as response:
                    parsed_body = await self._parse_response_body(response)

                    if response.status >= 400:
                        error_msg = (
                            parsed_body.get("detail")
                            if isinstance(parsed_body, dict)
                            else parsed_body
                        ) or f"HTTP {response.status}"
                        # A 4xx is TACTIC refusing the caller's request, not
                        # a fault, so it stays out of the error counts.
                        log = logger.error if response.status >= 500 else logger.warning
                        log(f"TACTIC request failed: {method} {url} - {error_msg}")
                        raise TacticError(
                            f"TACTIC service error: {error_msg}",
                            status=response.status,
                            body=parsed_body,
                        )

                    logger.debug(f"TACTIC request successful: {method} {url}")
                    return parsed_body

            except aiohttp.ClientError as e:
                if attempt <= self._max_retries and self._is_retryable(method, e):
                    backoff = 0.2 * attempt
                    logger.warning(
                        f"TACTIC client error (attempt {attempt}/{self._max_retries}): "
                        f"{method} {url} - {e!s}; retrying in {backoff:.1f}s"
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error(f"TACTIC client error: {method} {url} - {e!s}")
                raise TacticError(
                    f"Failed to communicate with TACTIC service: {e!s}"
                ) from e
            except TacticError:
                raise
            except Exception as e:
                logger.error(f"TACTIC request error: {method} {url} - {e!s}")
                raise TacticError(f"TACTIC request error: {e!s}") from e

    @staticmethod
    def _is_retryable(method: str, error: aiohttp.ClientError) -> bool:
        # A failed connect never reached TACTIC. Any later failure may have run
        # the operation already, so only reads are safe to repeat.
        return isinstance(error, aiohttp.ClientConnectorError) or method.upper() in {
            "GET",
            "HEAD",
            "OPTIONS",
        }

    def _normalize_query_params(self, params: dict | None) -> dict | None:
        """
        Normalize query params for aiohttp/yarl compatibility.

        yarl rejects raw bool values in query strings. Convert booleans to
        lowercase strings and drop None values.
        """
        if params is None:
            return None

        normalized: dict[str, Any] = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized[key] = "true" if value else "false"
            else:
                normalized[key] = value

        return normalized

    async def _parse_response_body(self, response: aiohttp.ClientResponse) -> Any:
        """Parse JSON if possible, otherwise return raw text for diagnostics."""
        try:
            return await response.json()
        except aiohttp.ContentTypeError:
            text = await response.text()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text

    async def start_radar_service(self, setup: MonitorSetup) -> dict[str, Any]:
        """Forward a monitor set up on catalogue readings to TACTIC."""
        return await self.request(
            method="POST",
            endpoint="/api/v1/orchestration/radar/services/start/",
            json_data=setup.model_dump(mode="json"),
        )

    async def stop_radar_service(self, service_id: str) -> dict[str, Any]:
        """Stop a RADAR service and remove its workload via TACTIC."""
        return await self.request(
            method="POST",
            endpoint=f"/api/v1/orchestration/radar/services/{path_segment(service_id)}/stop",
        )

    async def delete_radar_service(self, service_id: str) -> dict[str, Any]:
        """Delete a RADAR service and any backing workload via TACTIC."""
        return await self.request(
            method="DELETE",
            endpoint=f"/api/v1/orchestration/radar/services/{path_segment(service_id)}",
        )

    async def rename_radar_service(
        self, service_id: str, display_name: str
    ) -> dict[str, Any]:
        return await self.request(
            method="PATCH",
            endpoint=f"/api/v1/orchestration/radar/services/{path_segment(service_id)}/label",
            json_data={"display_name": display_name},
        )

    async def list_radar_services(
        self, active_only: bool = False
    ) -> list[dict[str, Any]]:
        """List RADAR services via TACTIC, optionally only the running ones."""
        return await self.request(
            method="GET",
            endpoint="/api/v1/orchestration/radar/services/",
            params={"active_only": active_only, "include_docker_status": False},
        )

    async def get_radar_service_details(self, service_id: str) -> dict[str, Any]:
        """One RADAR service with its configuration via TACTIC."""
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/orchestration/radar/services/{path_segment(service_id)}",
        )

    async def authenticate_user(self, email: str, password: str) -> dict[str, Any]:
        """Validate user credentials via TACTIC data service."""
        return await self.request(
            method="POST",
            endpoint="/api/v1/data/auth/login",
            json_data={"email": email, "password": password},
        )

    async def list_favorites(
        self, user_id: int, kind: str | None = None
    ) -> list[dict[str, Any]]:
        """A member's favorites, optionally of one kind."""
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            params={"kind": kind},
        )

    async def add_favorite(self, user_id: int, ref: FavoriteRef) -> dict[str, Any]:
        """Add a favorite; an existing one is returned unchanged."""
        return await self.request(
            method="POST",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            json_data=ref.model_dump(),
        )

    async def remove_favorite(self, user_id: int, ref: FavoriteRef) -> None:
        """Remove a favorite if the member has it."""
        await self.request(
            method="DELETE",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            params=ref.model_dump(),
        )

    async def list_available_models(
        self, strategy: str | None = None
    ) -> list[dict[str, Any]]:
        """List the shipped detectors, filtered by TACTIC when a strategy is given."""
        return await self.request(
            method="GET",
            endpoint="/api/v1/models/",
            params={"strategy": strategy} if strategy else None,
        )


tactic = Tactic()
