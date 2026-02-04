from functools import lru_cache

from pydantic import (
    BaseModel,
    FieldValidationInfo,
    SecretStr,
    field_validator,
)
from pydantic_settings import BaseSettings


class PionixConfig(BaseModel):
    """Configuration for Pionix API client."""

    # API Connection
    base_url: str = "https://cloud.pionix.com/api"
    api_key: SecretStr
    user_agent: str

    # Endpoint Templates
    chargers_endpoint: str
    device_model_endpoint: str
    telemetry_endpoint: str

    class Config:
        extra = "forbid"


class PionixSettings(BaseSettings):
    """Environment-backed settings for the Pionix API integration."""

    # Pionix API Configuration
    PIONIX_KEY: SecretStr
    PIONIX_USER_AGENT: str

    # Pionix API Endpoint Templates
    PIONIX_CHARGERS_ENDPOINT: str = "chargers"
    PIONIX_DEVICE_MODEL_ENDPOINT: str = "chargers/{charger_id}/deviceModel"
    PIONIX_TELEMETRY_ENDPOINT: str = "chargers/{charger_id}/telemetry/{hierarchy}"

    # MQTT Topic Templates
    PIONIX_MQTT_TELEMETRY_TOPIC: str = "charger/{charger_id}/live-telemetry/{hierarchy}"

    @field_validator(
        "PIONIX_DEVICE_MODEL_ENDPOINT",
        "PIONIX_TELEMETRY_ENDPOINT",
        "PIONIX_MQTT_TELEMETRY_TOPIC",
    )
    @classmethod
    def validate_endpoint_templates(cls, v: str, info: FieldValidationInfo) -> str:
        """Validate that endpoint templates contain expected placeholders."""
        required_placeholders = {
            "PIONIX_DEVICE_MODEL_ENDPOINT": ["{charger_id}"],
            "PIONIX_TELEMETRY_ENDPOINT": ["{charger_id}", "{hierarchy}"],
            "PIONIX_MQTT_TELEMETRY_TOPIC": ["{charger_id}", "{hierarchy}"],
        }

        field_name = info.field_name

        if field_name in required_placeholders:
            for placeholder in required_placeholders[field_name]:
                if placeholder not in v:
                    raise ValueError(
                        f"Field '{field_name}' template must contain {placeholder}"
                    )

        return v

    def build_mqtt_topic(self, charger_id: str, hierarchy: str) -> str:
        """Build MQTT topic with parameter substitution."""
        try:
            return self.PIONIX_MQTT_TELEMETRY_TOPIC.format(
                charger_id=charger_id, hierarchy=hierarchy
            )
        except KeyError as e:
            raise ValueError(f"Missing required parameter {e} for MQTT topic template")

    @property
    def pionix_config(self) -> PionixConfig:
        """Create PionixConfig instance from settings."""
        return PionixConfig(
            api_key=self.PIONIX_KEY,
            user_agent=self.PIONIX_USER_AGENT,
            chargers_endpoint=self.PIONIX_CHARGERS_ENDPOINT,
            device_model_endpoint=self.PIONIX_DEVICE_MODEL_ENDPOINT,
            telemetry_endpoint=self.PIONIX_TELEMETRY_ENDPOINT,
        )


@lru_cache(maxsize=1)
def get_pionix_settings() -> PionixSettings:
    """Return cached PionixSettings instance."""
    return PionixSettings()
