"""
API-Key Authentication Handler for Pionix Cloud MQTT Access

Simple authentication handler that uses API-Key for MQTT broker access,
replacing the complex Firebase authentication system.
"""

from typing import Optional, Tuple
from dataclasses import dataclass

from ...core.logs import logger


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

    pass


class ApiKeyAuthHandler:
    """
    Simple API-Key authentication handler for Pionix Cloud MQTT access

    This handler provides MQTT credentials using a username and API key,
    replacing the complex Firebase JWT token system with a simpler approach.
    """

    def __init__(self, username: str, api_key: str):
        self.username = username
        self.api_key = api_key
        self.credentials: Optional[ApiKeyCredentials] = None

        # Validate credentials on initialization
        if not username or not api_key:
            raise ApiKeyAuthError("Username and API key are required")

        self.credentials = ApiKeyCredentials(username=username, api_key=api_key)

        logger.info(f"API-Key authentication handler initialized for user: {username}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close authentication handler (no cleanup needed for API keys)"""
        logger.debug("API-Key authentication handler closed")

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

    async def get_mqtt_credentials(self) -> Tuple[str, str]:
        """
        Get MQTT credentials for Pionix Cloud broker

        Returns:
            Tuple of (username, api_key) for MQTT authentication

        Raises:
            ApiKeyAuthError: If no valid credentials available
        """
        if not self.credentials or not self.credentials.is_valid():
            raise ApiKeyAuthError(
                "No valid credentials available for MQTT authentication"
            )

        # For Pionix Cloud MQTT: username = user identifier, password = API key
        return self.credentials.username, self.credentials.api_key

    async def validate_connection(self) -> bool:
        """
        Validate API-Key credentials

        For API-Key authentication, we assume the credentials are valid
        if they are present. The actual validation happens during MQTT connection.

        Returns:
            True if credentials are present and formatted correctly
        """
        try:
            if not self.credentials:
                return False

            # Basic validation - check if credentials are non-empty
            if not self.credentials.is_valid():
                logger.warning(
                    "API-Key credentials validation failed: empty credentials"
                )
                return False

            logger.debug("API-Key credentials validation successful")
            return True

        except Exception as e:
            logger.error(f"Error validating API-Key credentials: {e}")
            return False

    def get_credentials_info(self) -> dict:
        """Get information about current credentials (for debugging/monitoring)"""
        if not self.credentials:
            return {"status": "no_credentials"}

        return {
            "status": "valid" if self.credentials.is_valid() else "invalid",
            "username": self.credentials.username,
            "api_key_length": (
                len(self.credentials.api_key) if self.credentials.api_key else 0
            ),
            "api_key_preview": (
                f"{self.credentials.api_key[:8]}..."
                if len(self.credentials.api_key) > 8
                else "***"
            ),
        }
