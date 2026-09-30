"""
Username/API-key authentication helper for MQTT broker access.
"""

from dataclasses import dataclass

from off_key_core.config.logs import logger


@dataclass
class ApiKeyCredentials:
    """API-Key authentication credentials"""

    username: str
    api_key: str

    def is_valid(self) -> bool:
        """Check if credentials are valid (non-empty)"""
        return bool(self.username and self.api_key)


class ApiKeyAuthError(Exception):
    """API-Key authentication error"""


class ApiKeyAuthHandler:
    """
    Simple username/API-key authentication handler for MQTT access.
    """

    def __init__(self, username: str, api_key: str):
        self.username = username
        self.api_key = api_key
        self.credentials: ApiKeyCredentials | None = None

        # Validate credentials on initialization
        if not username or not api_key:
            raise ApiKeyAuthError("Username and API key are required")

        self.credentials = ApiKeyCredentials(username=username, api_key=api_key)

        logger.info(f"API-Key authentication handler initialized for user: {username}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def stop(self):
        """Stop authentication handler (implements Stoppable protocol)"""
        # No cleanup needed for API key authentication
        logger.debug("API-Key authentication handler stopped")

    async def authenticate(self) -> ApiKeyCredentials:
        """
        Authenticate and return credentials

        For API-Key authentication, this simply validates and returns the credentials.
        No actual authentication request is needed.

        Returns:
            ApiKeyCredentials containing username and API key

        Raises:
            ApiKeyAuthError: If credentials are invalid
        """
        if not self.credentials or not self.credentials.is_valid():
            raise ApiKeyAuthError("Invalid or missing API-Key credentials")

        logger.info(
            f"API-Key authentication successful for user: {self.credentials.username}"
        )
        return self.credentials

    async def get_mqtt_credentials(self) -> tuple[str, str]:
        """
        Get MQTT credentials for broker authentication.

        Returns:
            Tuple of (username, api_key) for MQTT authentication

        Raises:
            ApiKeyAuthError: If no valid credentials available
        """
        if not self.credentials or not self.credentials.is_valid():
            raise ApiKeyAuthError(
                "No valid credentials available for MQTT authentication"
            )

        return self.credentials.username, self.credentials.api_key
