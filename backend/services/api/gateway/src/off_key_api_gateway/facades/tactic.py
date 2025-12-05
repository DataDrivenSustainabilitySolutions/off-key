"""
HTTP client for communicating with the TACTIC middleware service.
"""

import aiohttp
from typing import Dict, List, Optional, Any
from off_key_core.config.config import settings
from off_key_core.config.logs import logger


class Tactic:
    """
    Async HTTP client for communicating with TACTIC middleware service.
    """

    def __init__(self):
        self.base_url = settings.tactic_service_base_url
        self.timeout = aiohttp.ClientTimeout(total=30)
        logger.info(f"Tactic facade initialized with base URL: {self.base_url}")

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

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                ) as response:
                    response_data = await response.json()

                    if response.status >= 400:
                        error_msg = response_data.get(
                            "detail", f"HTTP {response.status}"
                        )
                        logger.error(
                            f"TACTIC request failed: {method} {url} - {error_msg}"
                        )
                        raise Exception(f"TACTIC service error: {error_msg}")

                    logger.debug(f"TACTIC request successful: {method} {url}")
                    return response_data

        except aiohttp.ClientError as e:
            logger.error(f"TACTIC client error: {method} {url} - {str(e)}")
            raise Exception(f"Failed to communicate with TACTIC service: {str(e)}")
        except Exception as e:
            logger.error(f"TACTIC request error: {method} {url} - {str(e)}")
            raise

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


# Global client instance
tactic = Tactic()
