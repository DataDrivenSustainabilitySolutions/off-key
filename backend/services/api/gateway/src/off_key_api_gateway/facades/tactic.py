"""
HTTP client for communicating with the TACTIC middleware service.
"""

import aiohttp
from typing import Dict, List, Optional, Any
from datetime import datetime
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
        self, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List RADAR services via TACTIC.

        Args:
            active_only: If True, only return active services

        Returns:
            List[Dict]: List of services
        """
        params = {"active_only": str(active_only).lower()}

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

    # =========================================================================
    # Data Services - Charger Management
    # =========================================================================

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
            "active_only": active_only,
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

    # =========================================================================
    # Data Services - Telemetry Management
    # =========================================================================

    async def get_telemetry_types(
        self, charger_id: str, limit: int = 100
    ) -> List[str]:
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
    ) -> Dict[str, Any]:
        """Get telemetry data from TACTIC data service."""
        params = {
            "limit": limit,
            "paginated": paginated,
        }
        if after_timestamp:
            params["after_timestamp"] = after_timestamp.isoformat()

        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/telemetry/{charger_id}/{telemetry_type}",
            params=params,
        )

    # =========================================================================
    # Data Services - User Management
    # =========================================================================

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email from TACTIC data service."""
        try:
            return await self._make_request(
                method="GET",
                endpoint=f"/api/v1/data/users/{email}",
            )
        except Exception as e:
            if "404" in str(e) or "not found" in str(e).lower():
                return None
            raise

    async def create_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create user via TACTIC data service."""
        return await self._make_request(
            method="POST",
            endpoint="/api/v1/data/users",
            json_data=user_data,
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
        params = {"new_password_hash": new_password_hash}
        return await self._make_request(
            method="PATCH",
            endpoint=f"/api/v1/data/users/{email}/password",
            params=params,
        )

    # =========================================================================
    # Data Services - Favorites Management
    # =========================================================================

    async def get_user_favorites(self, user_id: int) -> List[str]:
        """Get user favorites from TACTIC data service."""
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
        )

    async def add_user_favorite(
        self, user_id: int, charger_id: str
    ) -> Dict[str, str]:
        """Add user favorite via TACTIC data service."""
        params = {"charger_id": charger_id}
        return await self._make_request(
            method="POST",
            endpoint=f"/api/v1/data/users/{user_id}/favorites",
            params=params,
        )

    async def remove_user_favorite(
        self, user_id: int, charger_id: str
    ) -> Dict[str, str]:
        """Remove user favorite via TACTIC data service."""
        return await self._make_request(
            method="DELETE",
            endpoint=f"/api/v1/data/users/{user_id}/favorites/{charger_id}",
        )

    # =========================================================================
    # Data Services - Anomaly Management
    # =========================================================================

    async def get_charger_anomalies(
        self, charger_id: str, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Get anomalies for charger from TACTIC data service."""
        params = {"limit": limit}
        return await self._make_request(
            method="GET",
            endpoint=f"/api/v1/data/anomalies/{charger_id}",
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
        charger_id: str,
        timestamp: datetime,
        telemetry_type: str,
    ) -> Dict[str, str]:
        """Delete anomaly via TACTIC data service."""
        params = {
            "timestamp": timestamp.isoformat(),
            "telemetry_type": telemetry_type,
        }
        return await self._make_request(
            method="DELETE",
            endpoint=f"/api/v1/data/anomalies/{charger_id}",
            params=params,
        )


# Global client instance
tactic = Tactic()
