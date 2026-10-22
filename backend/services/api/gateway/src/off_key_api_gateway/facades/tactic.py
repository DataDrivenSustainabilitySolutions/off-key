"""
HTTP client for communicating with the TACTIC middleware service.
"""

import asyncio
import json
from datetime import datetime
from functools import cached_property
from typing import Any
from urllib.parse import quote

import aiohttp
from off_key_core.config.logs import correlation_headers, logger
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.config.services import get_service_endpoints_settings
from off_key_core.schemas.radar import RadarStartConfig


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
    ) -> Any:
        """
        Make an HTTP request to the TACTIC service.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.)
            endpoint: API endpoint path
            json_data: JSON payload for POST requests
            params: Query parameters

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
                    params=normalized_params,
                    headers={
                        **correlation_headers(),
                        **(headers or {}),
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
                        logger.error(
                            f"TACTIC request failed: {method} {url} - {error_msg}"
                        )
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

    async def start_radar_service(self, config: RadarStartConfig) -> dict[str, Any]:
        """Forward the canonical launch configuration to TACTIC."""
        return await self.request(
            method="POST",
            endpoint="/api/v1/orchestration/radar/services/start/",
            json_data=config.model_dump(
                mode="json",
                exclude={"display_name"} if config.display_name is None else None,
            ),
        )

    async def stop_radar_service(
        self,
        container_name: str | None = None,
        container_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Stop a RADAR service via TACTIC.

        Args:
            container_name: Name of the container to stop
            container_id: ID of the container to stop

        Returns:
            Dict: Service stop response
        """
        params = {}
        if container_name:
            params["container_name"] = container_name
        if container_id:
            params["container_id"] = container_id

        return await self.request(
            method="DELETE",
            endpoint="/api/v1/orchestration/radar/services/stop/",
            params=params,
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
        self, active_only: bool = False, include_docker_status: bool = False
    ) -> list[dict[str, Any]]:
        """
        List RADAR services via TACTIC.

        Args:
            active_only: If True, only return active services
            include_docker_status: If True, check actual Docker container status
                for each service (slower but more accurate)

        Returns:
            List[Dict]: List of services
        """
        params = {
            "active_only": str(active_only).lower(),
            "include_docker_status": str(include_docker_status).lower(),
        }

        return await self.request(
            method="GET",
            endpoint="/api/v1/orchestration/radar/services/",
            params=params,
        )

    async def get_radar_service_details(
        self,
        container_name: str | None = None,
        container_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Get RADAR service details via TACTIC.

        Args:
            container_name: Name of the container
            container_id: ID of the container

        Returns:
            Dict: Service details
        """
        params = {}
        if container_name:
            params["container_name"] = container_name
        if container_id:
            params["container_id"] = container_id

        return await self.request(
            method="GET",
            endpoint="/api/v1/orchestration/radar/services/details/",
            params=params,
        )

    async def get_chargers(
        self,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Get chargers from TACTIC data service."""
        params = {
            "skip": skip,
            "limit": limit,
            "active_only": str(active_only).lower(),
        }
        return await self.request(
            method="GET",
            endpoint="/api/v1/data/chargers",
            params=params,
        )

    async def get_active_charger_ids(
        self, skip: int = 0, limit: int = 100
    ) -> dict[str, list[str]]:
        """Get active charger IDs from TACTIC data service."""
        params = {"skip": skip, "limit": limit}
        return await self.request(
            method="GET",
            endpoint="/api/v1/data/chargers/active/ids",
            params=params,
        )

    async def get_telemetry_types(self, charger_id: str, limit: int = 100) -> list[str]:
        """Get telemetry types for a charger from TACTIC data service."""
        params = {"limit": limit}
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/telemetry/{path_segment(charger_id)}/types",
            params=params,
        )

    async def get_telemetry_data(
        self,
        charger_id: str,
        telemetry_type: str,
        limit: int = 1000,
        after_timestamp: datetime | None = None,
        after_created: datetime | None = None,
        after_event_timestamp: datetime | None = None,
        paginated: bool = False,
    ) -> Any:
        """Get telemetry data from TACTIC data service."""
        params: dict[str, Any] = {
            "type": telemetry_type,
            "limit": limit,
            "paginated": paginated,
        }
        if after_timestamp is not None:
            params["after_timestamp"] = after_timestamp.isoformat()
        if after_created is not None:
            if after_event_timestamp is None:
                raise ValueError("after_created requires after_event_timestamp")
            params["after_created"] = after_created.isoformat()
            params["after_event_timestamp"] = after_event_timestamp.isoformat()

        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/telemetry/{path_segment(charger_id)}",
            params=params,
        )

    async def authenticate_user(self, email: str, password: str) -> dict[str, Any]:
        """Validate user credentials via TACTIC data service."""
        return await self.request(
            method="POST",
            endpoint="/api/v1/data/auth/login",
            json_data={"email": email, "password": password},
        )

    async def get_user_favorites(self, user_id: int) -> list[str]:
        """Get user favorites from TACTIC data service."""
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
        )

    async def add_user_favorite(self, user_id: int, charger_id: str) -> dict[str, str]:
        """Add user favorite via TACTIC data service."""
        return await self.request(
            method="POST",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            json_data={"charger_id": charger_id},
        )

    async def remove_user_favorite(
        self, user_id: int, charger_id: str
    ) -> dict[str, str]:
        """Remove user favorite via TACTIC data service."""
        return await self.request(
            method="DELETE",
            endpoint=f"/api/v1/data/users/{user_id}/favorites/{path_segment(charger_id)}",
        )

    async def get_charger_anomalies(
        self,
        charger_id: str,
        limit: int = 500,
        telemetry_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get anomalies for charger from TACTIC data service."""
        params: dict[str, Any] = {"limit": limit}
        if telemetry_type:
            params["telemetry_type"] = telemetry_type
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/anomalies/{path_segment(charger_id)}",
            params=params,
        )

    async def get_anomaly_count(self, since: datetime | None = None) -> dict[str, int]:
        """Get total anomaly count, optionally filtered by timestamp."""
        params: dict[str, Any] = {}
        if since:
            params["since"] = since.isoformat()
        return await self.request(
            method="GET",
            endpoint="/api/v1/data/anomalies/count",
            params=params,
        )

    async def get_monitoring_evidence(
        self,
        *,
        charger_id: str,
        telemetry_type: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Get persisted static evidence for a charger and optional sensor."""
        params: dict[str, Any] = {"limit": limit}
        if telemetry_type:
            params["telemetry_type"] = telemetry_type
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/monitoring-evidence/{path_segment(charger_id)}",
            params=params,
        )

    async def get_monitoring_chart_evidence(
        self,
        *,
        charger_id: str,
        service_id: str | None = None,
        after_created: datetime | None = None,
        after_timestamp: datetime | None = None,
        after_service_id: str | None = None,
        after_sequence_number: int | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Get the compact, incrementally pageable chart evidence projection."""
        params: dict[str, Any] = {"limit": limit}
        if service_id is not None:
            params["service_id"] = service_id
        if after_created is not None:
            if (
                after_timestamp is None
                or after_service_id is None
                or after_sequence_number is None
            ):
                raise TacticError(
                    "after_timestamp, after_service_id and after_sequence_number "
                    "are required when after_created is provided"
                )
            params.update(
                {
                    "after_created": after_created.isoformat(),
                    "after_timestamp": after_timestamp.isoformat(),
                    "after_service_id": after_service_id,
                    "after_sequence_number": after_sequence_number,
                }
            )
        return await self.request(
            method="GET",
            endpoint=f"/api/v1/data/monitoring-evidence/{path_segment(charger_id)}/chart",
            params=params,
        )

    async def create_anomaly(self, anomaly_data: dict[str, Any]) -> dict[str, str]:
        """Create anomaly via TACTIC data service."""
        return await self.request(
            method="POST",
            endpoint="/api/v1/data/anomalies",
            json_data=anomaly_data,
        )

    async def delete_anomaly(
        self,
        anomaly_id: str,
    ) -> dict[str, str]:
        """Delete anomaly via TACTIC data service."""
        return await self.request(
            method="DELETE",
            endpoint=f"/api/v1/data/anomalies/{path_segment(anomaly_id)}",
        )

    async def list_available_models(self) -> list[dict[str, Any]]:
        """List models from TACTIC model registry API."""
        return await self.request(
            method="GET",
            endpoint="/api/v1/models/",
        )


tactic = Tactic()


def get_tactic_client() -> Tactic:
    """Return the process-wide TACTIC client."""
    return tactic
