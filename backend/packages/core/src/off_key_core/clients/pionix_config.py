"""
Pionix API Configuration

Pure data container for Pionix API configuration.
Contains no behavior - just validated configuration values.
"""

from pydantic import BaseModel, SecretStr


class PionixConfig(BaseModel):
    """
    Configuration for Pionix API client.

    This is a pure data model containing only configuration values.
    """

    # API Connection
    base_url: str = "https://cloud.pionix.com/api"
    api_key: SecretStr
    user_agent: str

    # Endpoint Templates
    chargers_endpoint: str
    device_model_endpoint: str
    telemetry_endpoint: str

    class Config:
        # Prevent extra fields
        extra = "forbid"
