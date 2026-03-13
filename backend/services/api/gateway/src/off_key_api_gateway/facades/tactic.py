"""
HTTP client for communicating with the TACTIC middleware service.
"""

import asyncio
import json
from datetime import datetime
from functools import lru_cache
from typing import Dict, List, Optional, Any, cast

import aiohttp
from off_key_core.config.services import get_service_endpoints_settings
from off_key_core.config.logs import logger


class TacticError(Exception):
    """Typed error for TACTIC HTTP failures."""

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class Tactic:
    """
    Async HTTP client for communicating with TACTIC middleware service.
    """

    def __init__(self):
        self.base_url = get_service_endpoints_settings().tactic_service_base_url
        self.timeout = aiohttp.ClientTimeout(total=30)
        self._session: Optional[aiohttp.ClientSession] = None
        self._max_retries = 2
        logger.info(f"Tactic facade initialized with base URL: {self.base_url}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Create or reuse a shared aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the shared session if it exists."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
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
                if attempt <= self._max_retries:
                    backoff = 0.2 * attempt
                    logger.warning(
                        f"TACTIC client error (attempt {attempt}/{self._max_retries}): "
                        f"{method} {url} - {str(e)}; retrying in {backoff:.1f}s"
                    )
                    await asyncio.sleep(backoff)
                    continue
                logger.error(f"TACTIC client error: {method} {url} - {str(e)}")
                raise TacticError(
                    f"Failed to communicate with TACTIC service: {str(e)}"
                )
            except TacticError:
                raise
            except Exception as e:
                logger.error(f"TACTIC request error: {method} {url} - {str(e)}")
                raise TacticError(f"TACTIC request error: {str(e)}")

    def _normalize_query_params(self, params: Optional[Dict]) -> Optional[Dict]:
        """
        Normalize query params for aiohttp/yarl compatibility.

        yarl rejects raw bool values in query strings. Convert booleans to
        lowercase strings and drop None values.
        """
        if params is None:
            return None

        normalized: Dict[str, Any] = {}
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

    async def start_radar_service(
        self,
        container_name: str,
        mqtt_topics: List[str],
        model_type: str = "isolation_forest",
        model_params: Optional[Dict[str, Any]] = None,
        preprocessing_steps: Optional[List[Dict[str, Any]]] = None,
        mqtt_config: Optional[Dict[str, Any]] = None,
        anomaly_thresholds: Optional[Dict[str, float]] = None,
        performance_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start a new RADAR service via TACTIC.

        Args:
            container_name: Name for the Docker container
            mqtt_topics: List of MQTT topics to monitor
            model_type: ML model type
            model_params: Model-specific parameters
            preprocessing_steps: Optional preprocessing steps for data transformation
            mqtt_config: MQTT configuration
            anomaly_thresholds: Anomaly detection thresholds
            performance_config: Performance settings

        Returns:
            Dict: Service creation response
        """
        payload = {
            "container_name": container_name,
            "mqtt_topics": mqtt_topics,
            "model_type": model_type,
        }

        if model_params:
            payload["model_params"] = model_params
        if preprocessing_steps:
            payload["preprocessing_steps"] = preprocessing_steps
        if mqtt_config:
            payload["mqtt_config"] = mqtt_config
        if anomaly_thresholds:
            payload["anomaly_thresholds"] = anomaly_thresholds
        if performance_config:
            payload["performance_config"] = performance_config

        return await self._make_request(
            method="POST",
            endpoint="/api/v1/orchestration/radar/services/start/",
            json_data=payload,
        )

    async def stop_radar_service(
        self,
        container_name: Optional[str] = None,
        container_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Stop a RADAR service via TACTIC.

        Args:
            container_name: Name of the container to stop
            container_id: ID of the container to stop

        Returns:
            Dict: Service stop response
        """
        if not container_name and not container_id:
            raise TacticError(
                "Either container_name or container_id is required to stop a service"
            )

        params = {}
        if container_name:
            params["container_name"] = container_name
        if container_id:
            params["container_id"] = container_id

        return await self._make_request(
            method="DELETE",
            endpoint="/api/v1/orchestration/radar/services/stop/",
            params=params,
        )

    async def list_radar_services(
        self, active_only: bool = False, include_docker_status: bool = False
    ) -> List[Dict[str, Any]]:
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

        return await self._make_request(
            method="GET",
            endpoint="/api/v1/orchestration/radar/services/",
            params=params,
        )

    async def get_radar_service_details(
        self,
        container_name: Optional[str] = None,
        container_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get RADAR service details via TACTIC.

        Args:
            container_name: Name of the container
            container_id: ID of the container

        Returns:
            Dict: Service details
        """
        if not container_name and not container_id:
            raise TacticError(
                "Either container_name or container_id is required to get details"
            )

        params = {}
        if container_name:
            params["container_name"] = container_name
        if container_id:
            params["container_id"] = container_id

        return await self._make_request(
            method="GET",
            endpoint="/api/v1/orchestration/radar/services/details/",
            params=params,
        )

    async def get_chargers(
        self,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get chargers from TACTIC data service."""
        params = {
            "skip": skip,
            "limit": limit,
            "active_only": str(active_only).lower(),
        }
        return await self._make_request(
            method="GET",
            endpoint="/api/v1/data/chargers",
            params=params,
        )

    async def get_active_charger_ids(
        self, skip: int = 0, limit: int = 100
    ) -> Dict[str, List[str]]:
        """Get active charger IDs from TACTIC data service."""
        params = {"skip": skip, "limit": limit}
        return await self._make_request(
            method="GET",
            endpoint="/api/v1/data/chargers/active/ids",
            params=params,
        )

    async def get_telemetry_types(self, charger_id: str, limit: int = 100) -> List[str]:
        """Get telemetry types for a charger from TACTIC data service."""
        params = {"limit": limit}
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/telemetry/{charger_id}/types",
            params=params,
        )

    async def get_telemetry_data(
        self,
        charger_id: str,
        telemetry_type: str,
        limit: int = 1000,
        after_timestamp: Optional[datetime] = None,
        paginated: bool = False,
    ) -> Any:
        """Get telemetry data from TACTIC data service."""
        params: Dict[str, Any] = {
            "type": telemetry_type,
            "limit": limit,
            "paginated": paginated,
        }
        if after_timestamp is not None:
            params["after_timestamp"] = after_timestamp.isoformat()

        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/telemetry/{charger_id}",
            params=params,
        )

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email from TACTIC data service."""
        try:
            return await self._make_request(
                method="GET",
                endpoint=f"/api/v1/data/users/{email}",
            )
        except TacticError as e:
            if e.status == 404:
                return None
            raise

    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create user via TACTIC data service."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/data/users",
            json_data=user_data,
        )

    async def authenticate_user(self, email: str, password: str) -> Dict[str, Any]:
        """Validate user credentials via TACTIC data service."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/data/auth/login",
            json_data={"email": email, "password": password},
        )

    async def verify_user_email(self, email: str) -> Dict[str, str]:
        """Verify user email via TACTIC data service."""
        return await self._make_request(
            method="PATCH",
            endpoint=f"/api/v1/data/users/{email}/verify",
        )

    async def update_user_password(
        self, email: str, new_password_hash: str
    ) -> Dict[str, str]:
        """Update user password via TACTIC data service."""
        return await self._make_request(
            method="PATCH",
            endpoint=f"/api/v1/data/users/{email}/password",
            json_data={"new_password_hash": new_password_hash},
        )

    async def get_user_favorites(self, user_id: int) -> List[str]:
        """Get user favorites from TACTIC data service."""
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
        )

    async def add_user_favorite(self, user_id: int, charger_id: str) -> Dict[str, str]:
        """Add user favorite via TACTIC data service."""
        return await self._make_request(
            method="POST",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            json_data={"charger_id": charger_id},
        )

    async def remove_user_favorite(
        self, user_id: int, charger_id: str
    ) -> Dict[str, str]:
        """Remove user favorite via TACTIC data service."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/api/v1/data/users/{user_id}/favorites/{charger_id}",
        )

    async def get_charger_anomalies(
        self,
        charger_id: str,
        limit: int = 500,
        telemetry_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get anomalies for charger from TACTIC data service."""
        params: Dict[str, Any] = {"limit": limit}
        if telemetry_type:
            params["telemetry_type"] = telemetry_type
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/anomalies/{charger_id}",
            params=params,
        )

    async def get_anomaly_count(
        self, since: Optional[datetime] = None
    ) -> Dict[str, int]:
        """Get total anomaly count, optionally filtered by timestamp."""
        params: Dict[str, Any] = {}
        if since:
            params["since"] = since.isoformat()
        return await self._make_request(
            method="GET",
            endpoint="/api/v1/data/anomalies/count",
            params=params,
        )

    async def create_anomaly(self, anomaly_data: Dict[str, Any]) -> Dict[str, str]:
        """Create anomaly via TACTIC data service."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/data/anomalies",
            json_data=anomaly_data,
        )

    async def delete_anomaly(
        self,
        anomaly_id: str,
    ) -> Dict[str, str]:
        """Delete anomaly via TACTIC data service."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/api/v1/data/anomalies/{anomaly_id}",
        )

    async def list_available_models(self) -> List[Dict[str, Any]]:
        """List models from TACTIC model registry API."""
        return await self._make_request(
            method="GET",
            endpoint="/api/v1/models/",
        )

    async def list_available_preprocessors(self) -> List[Dict[str, Any]]:
        """List preprocessors from TACTIC model registry API."""
        return await self._make_request(
            method="GET",
            endpoint="/api/v1/models/preprocessors",
        )


@lru_cache(maxsize=1)
def get_tactic_client() -> Tactic:
    """Return cached tactic client instance."""
    return Tactic()


class _LazyTacticFacade:
    """Attribute-forwarding facade that defers Tactic creation until first use."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_tactic_client(), name)


# Global facade for existing callsites without import-time Tactic initialization.
tactic = cast(Tactic, _LazyTacticFacade())
