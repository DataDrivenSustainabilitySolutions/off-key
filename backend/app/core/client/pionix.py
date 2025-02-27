import httpx
from typing import Optional, Dict, Any

from ...core.logs import logger


class PionixClient:
    def __init__(self, api_key: str, user_agent: str):
        self.base_url = "https://sc-main.schoneberg.pionix.net"
        if self.base_url.endswith("/"):
            self.base_url = self.base_url.rstrip("/")
        self.api_key = api_key
        self.user_agent = user_agent
        self.client = httpx.AsyncClient()  # Reuse the client for connection pooling

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

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
            "User-Agent": self.user_agent,
            "X-APIKEY": self.api_key,
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
            "User-Agent": self.user_agent,
            "X-APIKEY": self.api_key,
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
