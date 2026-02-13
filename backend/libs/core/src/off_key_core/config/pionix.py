from functools import lru_cache

from pydantic import BaseModel, SecretStr, ValidationInfo, field_validator

from .config import PionixConfig, get_settings


class PionixSettings(BaseModel):
    """Pionix API and MQTT template settings."""

    PIONIX_KEY: SecretStr
    PIONIX_USER_AGENT: str
    PIONIX_CHARGERS_ENDPOINT: str
    PIONIX_DEVICE_MODEL_ENDPOINT: str
    PIONIX_TELEMETRY_ENDPOINT: str
    PIONIX_MQTT_TELEMETRY_TOPIC: str

    @field_validator(
        "PIONIX_DEVICE_MODEL_ENDPOINT",
        "PIONIX_TELEMETRY_ENDPOINT",
        "PIONIX_MQTT_TELEMETRY_TOPIC",
    )
    @classmethod
    def validate_endpoint_templates(cls, value: str, info: ValidationInfo) -> str:
        required_placeholders = {
            "PIONIX_DEVICE_MODEL_ENDPOINT": ["{charger_id}"],
            "PIONIX_TELEMETRY_ENDPOINT": ["{charger_id}", "{hierarchy}"],
            "PIONIX_MQTT_TELEMETRY_TOPIC": ["{charger_id}", "{hierarchy}"],
        }
        for placeholder in required_placeholders.get(info.field_name, []):
            if placeholder not in value:
                raise ValueError(
                    f"Field '{info.field_name}' template must contain {placeholder}"
                )
        return value

    @property
    def pionix_config(self) -> PionixConfig:
        return PionixConfig(
            api_key=self.PIONIX_KEY,
            user_agent=self.PIONIX_USER_AGENT,
            chargers_endpoint=self.PIONIX_CHARGERS_ENDPOINT,
            device_model_endpoint=self.PIONIX_DEVICE_MODEL_ENDPOINT,
            telemetry_endpoint=self.PIONIX_TELEMETRY_ENDPOINT,
        )

    def build_mqtt_topic(self, charger_id: str, hierarchy: str) -> str:
        try:
            return self.PIONIX_MQTT_TELEMETRY_TOPIC.format(
                charger_id=charger_id,
                hierarchy=hierarchy,
            )
        except KeyError as exc:
            raise ValueError(
                f"Missing required parameter {exc} for MQTT topic template"
            ) from exc


@lru_cache(maxsize=1)
def get_pionix_settings() -> PionixSettings:
    """Return cached PionixSettings view derived from canonical Settings."""
    settings = get_settings()
    return PionixSettings(
        PIONIX_KEY=settings.PIONIX_KEY,
        PIONIX_USER_AGENT=settings.PIONIX_USER_AGENT,
        PIONIX_CHARGERS_ENDPOINT=settings.PIONIX_CHARGERS_ENDPOINT,
        PIONIX_DEVICE_MODEL_ENDPOINT=settings.PIONIX_DEVICE_MODEL_ENDPOINT,
        PIONIX_TELEMETRY_ENDPOINT=settings.PIONIX_TELEMETRY_ENDPOINT,
        PIONIX_MQTT_TELEMETRY_TOPIC=settings.PIONIX_MQTT_TELEMETRY_TOPIC,
    )
