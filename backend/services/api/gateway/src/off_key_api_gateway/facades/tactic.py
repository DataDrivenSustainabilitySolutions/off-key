"""
HTTP client for communicating with the TACTIC middleware service.
"""

import asyncio
import json
from typing import Dict, List, Optional, Any

import aiohttp
from off_key_core.config.config import get_settings
from off_key_core.config.logs import logger

settings = get_settings()


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
        self.base_url = settings.tactic_service_base_url
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
    ) -> Dict[str, Any]:
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

        attempt = 0
        while True:
            attempt += 1
            try:
                session = await self._get_session()
                async with session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
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


# Global client instance
tactic = Tactic()
