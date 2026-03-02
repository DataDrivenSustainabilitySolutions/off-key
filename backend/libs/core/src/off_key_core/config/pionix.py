from functools import lru_cache

from pydantic import BaseModel, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PionixConfig(BaseModel):
    """Configuration for Pionix API client."""

    base_url: str = "https://cloud.pionix.com/api"
    api_key: SecretStr
    user_agent: str
    chargers_endpoint: str
    device_model_endpoint: str
    telemetry_endpoint: str

    class Config:
        extra = "forbid"


class PionixSettings(BaseSettings):
    """Pionix API and MQTT template settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    PIONIX_KEY: SecretStr
    PIONIX_USER_AGENT: str
    PIONIX_CHARGERS_ENDPOINT: str = "chargers"
    PIONIX_DEVICE_MODEL_ENDPOINT: str = "chargers/{charger_id}/deviceModel"
    PIONIX_TELEMETRY_ENDPOINT: str = "chargers/{charger_id}/telemetry/{hierarchy}"
    PIONIX_MQTT_TELEMETRY_TOPIC: str = "charger/{charger_id}/live-telemetry/{hierarchy}"

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
    """Return cached Pionix settings."""
    return PionixSettings()
