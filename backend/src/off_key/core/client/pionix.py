"""
Pionix API Client

Self-contained facade for interacting with the Pionix API.
Encapsulates all URL building logic and provides high-level methods.
"""

import httpx
from typing import Optional, Dict, Any, List
from urllib.parse import quote

from .pionix_config import PionixConfig
from ...core.logs import logger


class PionixClient:
    """
    Facade for Pionix API interactions.

    This client encapsulates all logic for communicating with the Pionix API,
    including URL construction, authentication, and high-level operations.
    """

    def __init__(self, config: PionixConfig):
        """
        Initialize the Pionix client with configuration.

        Args:
            config: PionixConfig object containing all necessary configuration
        """
        self.config = config
        self.base_url = config.base_url
        self.client = httpx.AsyncClient()  # Reuse the client for connection pooling

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    def _build_url(self, endpoint_name: str, **params) -> str:
        """
        Private method to build Pionix API URL with parameter substitution.

        Args:
            endpoint_name: Name of the endpoint template to use
            **params: Parameters to substitute in template

        Returns:
            Formatted URL string with parameters substituted

        Raises:
            ValueError: If required parameters are missing or endpoint doesn't exist
        """
        endpoint_mapping = {
            "chargers": self.config.chargers_endpoint,
            "device_model": self.config.device_model_endpoint,
            "telemetry": self.config.telemetry_endpoint,
        }

        if endpoint_name not in endpoint_mapping:
            raise ValueError(f"Unknown endpoint: {endpoint_name}")

        template = endpoint_mapping[endpoint_name]

        # URL encode parameters that may contain special characters
        encoded_params = {}
        for key, value in params.items():
            if key == "hierarchy" and "/" in str(value):
                # Special handling for hierarchy paths - URL encode forward slashes
                encoded_params[key] = quote(str(value), safe="")
            else:
                encoded_params[key] = str(value)

        try:
            return template.format(**encoded_params)
        except KeyError as e:
            raise ValueError(
                f"Missing required parameter {e} for endpoint {endpoint_name}"
            )

    def _build_telemetry_url(
        self, charger_id: str, hierarchy: str, limit: Optional[int] = None
    ) -> str:
        """
        Private method to build telemetry URL with optional query parameters.

        Args:
            charger_id: Charger ID
            hierarchy: Telemetry hierarchy path
            limit: Optional limit parameter

        Returns:
            Complete telemetry URL with query parameters
        """
        base_url = self._build_url(
            "telemetry", charger_id=charger_id, hierarchy=hierarchy
        )

        if limit is not None:
            base_url += f"?Limit={limit}"

        return base_url

    async def get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform an asynchronous GET request.

        Args:
            endpoint: The API endpoint to call.
            params: Optional query parameters.

        Returns:
            The JSON response as a dictionary.

        Raises:
            httpx.HTTPStatusError: If the response status code is 4xx or 5xx.
            httpx.RequestError: If there is a network-related error.
            ValueError: If the response cannot be decoded as JSON.
        """
        headers = {
            "User-Agent": self.config.user_agent,
            "X-APIKEY": self.config.api_key.get_secret_value(),
        }
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"GET request to {url} with params {params}")

        try:
            response = await self.client.get(
                url,
                headers=headers,
                params=params,
                timeout=30.0,  # Add a timeout to prevent hanging requests
            )
            logger.info(f"GET response from {url} - Status: {response.status_code}")
            logger.debug(f"Response content: {response.text}")

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e} - Response: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Network error occurred: {e}")
            raise
        except ValueError as e:
            logger.error(f"Failed to decode JSON response: {e}")
            raise

    async def post(
        self, endpoint: str, json: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform an asynchronous POST request.

        Args:
            endpoint: The API endpoint to call.
            json: Optional JSON payload.

        Returns:
            The JSON response as a dictionary.

        Raises:
            httpx.HTTPStatusError: If the response status code is 4xx or 5xx.
            httpx.RequestError: If there is a network-related error.
            ValueError: If the response cannot be decoded as JSON.
        """
        headers = {
            "User-Agent": self.config.user_agent,
            "X-APIKEY": self.config.api_key.get_secret_value(),
        }
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"POST request to {url} with payload {json}")

        try:
            response = await self.client.post(
                url,
                headers=headers,
                json=json,
                timeout=30.0,  # Add a timeout to prevent hanging requests
            )
            logger.info(f"POST response from {url} - Status: {response.status_code}")
            logger.debug(f"Response content: {response.text}")

            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred: {e} - Response: {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Network error occurred: {e}")
            raise
        except ValueError as e:
            logger.error(f"Failed to decode JSON response: {e}")
            raise

    # High-level public methods for Pionix API operations

    async def get_chargers(self) -> List[Dict[str, Any]]:
        """
        Get all active chargers.

        Returns:
            List of charger data dictionaries
        """
        logger.info("Fetching all active chargers")
        return await self.get(self.config.chargers_endpoint)

    async def get_device_info(self, charger_id: str) -> Dict[str, Any]:
        """
        Get device information/model for a specific charger.

        Args:
            charger_id: The ID of the charger

        Returns:
            Device model data dictionary
        """
        logger.info(f"Fetching device model for charger {charger_id}")
        url = self._build_url("device_model", charger_id=charger_id)
        return await self.get(url)

    async def get_telemetry_data(
        self, charger_id: str, hierarchy: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get telemetry data for a specific charger and hierarchy.

        Args:
            charger_id: The ID of the charger
            hierarchy: The telemetry hierarchy path
            limit: Optional limit on number of records to retrieve

        Returns:
            Telemetry data dictionary with items list
        """
        logger.info(
            f"Fetching telemetry for charger {charger_id}, "
            f"hierarchy {hierarchy}, limit {limit}"
        )
        url = self._build_telemetry_url(charger_id, hierarchy, limit)
        return await self.get(url)
