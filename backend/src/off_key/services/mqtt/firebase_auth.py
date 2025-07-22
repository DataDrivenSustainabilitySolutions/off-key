"""
Firebase Authentication Handler for Pionix Cloud MQTT Access

Handles Firebase auth including login, token refresh, and credential management
for accessing the Pionix Cloud MQTT broker.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

import httpx
from ...core.logs import logger
from .config import FirebaseConfig


@dataclass
class FirebaseCredentials:
    """Firebase authentication credentials"""

    uid: str
    id_token: str
    refresh_token: str
    expires_at: datetime
    email: str

    @property
    def is_expired(self) -> bool:
        """Check if credentials are expired"""
        return datetime.now() >= self.expires_at - timedelta(
            minutes=5
        )  # 5 minute buffer

    @property
    def time_until_expiry(self) -> float:
        """Get seconds until expiry"""
        return (self.expires_at - datetime.now()).total_seconds()


class FirebaseAuthError(Exception):
    """Firebase authentication error"""

    pass


class FirebaseAuthHandler:
    """
    Firebase authentication handler for Pionix Cloud MQTT access

    Handles:
    - Email/password authentication
    - Token refresh
    - Credential management
    - Error handling and retries
    """

    def __init__(self, config: FirebaseConfig):
        self.config = config
        self.credentials: Optional[FirebaseCredentials] = None
        self.client = httpx.AsyncClient(timeout=30.0)
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        """Close HTTP client and cancel refresh task"""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        await self.client.aclose()

    async def authenticate(self, email: str, password: str) -> FirebaseCredentials:
        """
        Authenticate with Firebase using email/password

        Args:
            email: Firebase user email
            password: Firebase user password

        Returns:
            Firebase credentials

        Raises:
            FirebaseAuthError: If authentication fails
        """
        logger.info(f"Authenticating with Firebase for email: {email}")

        try:
            auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={self.config.api_key}"

            payload = {"email": email, "password": password, "returnSecureToken": True}

            response = await self.client.post(auth_url, json=payload)

            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                error_message = error_data.get("error", {}).get(
                    "message", "Unknown error"
                )
                logger.error(f"Firebase authentication failed: {error_message}")
                raise FirebaseAuthError(f"Authentication failed: {error_message}")

            auth_data = response.json()

            # Parse expiration
            expires_in = int(auth_data.get("expiresIn", 3600))
            expires_at = datetime.now() + timedelta(seconds=expires_in)

            credentials = FirebaseCredentials(
                uid=auth_data["localId"],
                id_token=auth_data["idToken"],
                refresh_token=auth_data["refreshToken"],
                expires_at=expires_at,
                email=email,
            )

            self.credentials = credentials
            logger.info(
                f"Firebase authentication successful for UID: {credentials.uid}"
            )

            # Start automatic token refresh
            self._start_token_refresh()

            return credentials

        except httpx.HTTPError as e:
            logger.error(f"HTTP error during Firebase authentication: {e}")
            raise FirebaseAuthError(f"HTTP error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during Firebase authentication: {e}")
            raise FirebaseAuthError(f"Unexpected error: {e}")

    async def refresh_token(self) -> FirebaseCredentials:
        """
        Refresh Firebase token using refresh token

        Returns:
            Updated Firebase credentials

        Raises:
            FirebaseAuthError: If token refresh fails
        """
        async with self._refresh_lock:
            if not self.credentials:
                raise FirebaseAuthError("No credentials available for refresh")

            if not self.credentials.is_expired:
                return self.credentials

            logger.info("Refreshing Firebase token")

            try:
                refresh_url = f"https://securetoken.googleapis.com/v1/token?key={self.config.api_key}"

                payload = {
                    "grant_type": "refresh_token",
                    "refresh_token": self.credentials.refresh_token,
                }

                response = await self.client.post(refresh_url, json=payload)

                if response.status_code != 200:
                    error_data = response.json() if response.content else {}
                    error_message = error_data.get("error", {}).get(
                        "message", "Unknown error"
                    )
                    logger.error(f"Firebase token refresh failed: {error_message}")
                    raise FirebaseAuthError(f"Token refresh failed: {error_message}")

                refresh_data = response.json()

                # Parse expiration
                expires_in = int(refresh_data.get("expires_in", 3600))
                expires_at = datetime.now() + timedelta(seconds=expires_in)

                # Update credentials
                self.credentials.id_token = refresh_data["id_token"]
                self.credentials.refresh_token = refresh_data["refresh_token"]
                self.credentials.expires_at = expires_at

                logger.info("Firebase token refreshed successfully")
                return self.credentials

            except httpx.HTTPError as e:
                logger.error(f"HTTP error during token refresh: {e}")
                raise FirebaseAuthError(f"HTTP error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error during token refresh: {e}")
                raise FirebaseAuthError(f"Unexpected error: {e}")

    async def get_valid_credentials(self) -> FirebaseCredentials:
        """
        Get valid Firebase credentials, refreshing if necessary

        Returns:
            Valid Firebase credentials

        Raises:
            FirebaseAuthError: If no valid credentials available
        """
        if not self.credentials:
            raise FirebaseAuthError(
                "No credentials available. Please authenticate first."
            )

        if self.credentials.is_expired:
            await self.refresh_token()

        return self.credentials

    def _start_token_refresh(self):
        """Start automatic token refresh task"""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()

        self._refresh_task = asyncio.create_task(self._token_refresh_loop())

    async def _token_refresh_loop(self):
        """Background task to automatically refresh tokens"""
        try:
            while True:
                if not self.credentials:
                    break

                # Calculate sleep time until next refresh (5 minutes before expiry)
                sleep_time = max(60, self.credentials.time_until_expiry - 300)

                logger.debug(f"Token refresh scheduled in {sleep_time:.0f} seconds")
                await asyncio.sleep(sleep_time)

                try:
                    await self.refresh_token()
                except FirebaseAuthError as e:
                    logger.error(f"Automatic token refresh failed: {e}")
                    # Continue loop to retry
                    await asyncio.sleep(60)  # Wait 1 minute before retry

        except asyncio.CancelledError:
            logger.info("Token refresh loop cancelled")
        except Exception as e:
            logger.error(f"Unexpected error in token refresh loop: {e}")

    async def validate_connection(self) -> bool:
        """
        Validate Firebase connection and credentials

        Returns:
            True if connection is valid, False otherwise
        """
        try:
            if not self.credentials:
                return False

            # Try to get user info to validate token
            info_url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={self.config.api_key}"

            payload = {"idToken": self.credentials.id_token}

            response = await self.client.post(info_url, json=payload)

            if response.status_code == 200:
                logger.debug("Firebase connection validation successful")
                return True
            else:
                logger.warning(
                    f"Firebase connection validation failed: {response.status_code}"
                )
                return False

        except Exception as e:
            logger.error(f"Error validating Firebase connection: {e}")
            return False

    async def get_mqtt_credentials(self) -> tuple[str, str]:
        """
        Get MQTT credentials for Pionix Cloud broker
        Automatically refreshes token if expired.

        Returns:
            Tuple of (username, password) for MQTT authentication

        Raises:
            FirebaseAuthError: If no valid credentials available
        """
        if not self.credentials:
            raise FirebaseAuthError("No credentials available for MQTT authentication")

        # Automatically refresh if expired
        if self.credentials.is_expired:
            logger.info("MQTT credentials expired, refreshing token...")
            await self.refresh_token()

        # For Pionix Cloud MQTT: username = Firebase UID, password = Firebase ID token
        return self.credentials.uid, self.credentials.id_token
