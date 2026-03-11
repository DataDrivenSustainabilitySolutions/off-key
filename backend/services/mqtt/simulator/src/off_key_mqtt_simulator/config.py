"""Configuration for MQTT simulator service."""

from functools import lru_cache
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool
    broker_host: str
    broker_port: int
    use_tls: bool
    use_auth: bool
    username: str
    api_key: str
    client_id_prefix: str
    interval_seconds: float
    qos: int
    charger_ids: list[str]
    features: list[str]
    topic_template: str
    payload_charger_key: str
    payload_type_key: str
    value_min: float
    value_max: float
    blip_probability: float
    blip_multiplier_min: float
    blip_multiplier_max: float

    @field_validator("broker_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("Broker port must be between 1 and 65535")
        return value

    @field_validator("interval_seconds")
    @classmethod
    def validate_interval(cls, value: float) -> float:
        if not 0.1 <= value <= 3600.0:
            raise ValueError("Interval must be between 0.1 and 3600 seconds")
        return value

    @field_validator("qos")
    @classmethod
    def validate_qos(cls, value: int) -> int:
        if value not in {0, 1, 2}:
            raise ValueError("QoS must be one of: 0, 1, 2")
        return value

    @field_validator("features")
    @classmethod
    def validate_features(cls, value: list[str]) -> list[str]:
        normalized = [feature.strip() for feature in value if feature.strip()]
        if not 1 <= len(normalized) <= 3:
            raise ValueError("Simulator must publish 1 to 3 synthetic features")
        return normalized

    @field_validator("charger_ids")
    @classmethod
    def validate_charger_ids(cls, value: list[str]) -> list[str]:
        normalized = [charger_id.strip() for charger_id in value if charger_id.strip()]
        if not normalized:
            raise ValueError("At least one charger ID is required")
        return normalized

    @field_validator("blip_probability")
    @classmethod
    def validate_blip_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Blip probability must be between 0.0 and 1.0")
        return value

    @field_validator("blip_multiplier_min")
    @classmethod
    def validate_blip_multiplier_min(cls, value: float) -> float:
        if value < 1.0:
            raise ValueError("Blip multiplier min must be >= 1.0")
        return value

    @field_validator("blip_multiplier_max")
    @classmethod
    def validate_blip_multiplier_max(cls, value: float) -> float:
        if value < 1.0:
            raise ValueError("Blip multiplier max must be >= 1.0")
        return value

    @field_validator("value_max")
    @classmethod
    def validate_range_max(cls, value: float, info) -> float:
        value_min = info.data.get("value_min")
        if value_min is not None and value < value_min:
            raise ValueError("value_max must be >= value_min")
        return value

    @field_validator("blip_multiplier_max")
    @classmethod
    def validate_blip_multiplier_range(cls, value: float, info) -> float:
        blip_multiplier_min = info.data.get("blip_multiplier_min")
        if blip_multiplier_min is not None and value < blip_multiplier_min:
            raise ValueError("blip_multiplier_max must be >= blip_multiplier_min")
        return value


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    SIMULATOR_ENABLED: bool = True
    SIMULATOR_BROKER_HOST: str = "source-broker"
    SIMULATOR_BROKER_PORT: int = 1883
    SIMULATOR_USE_TLS: bool = False
    SIMULATOR_USE_AUTH: bool = False
    SIMULATOR_USERNAME: str = ""
    SIMULATOR_API_KEY: str = ""
    SIMULATOR_CLIENT_ID_PREFIX: str = "offkey-simulator"
    SIMULATOR_INTERVAL_SECONDS: float = 1.0
    SIMULATOR_QOS: int = 0
    SIMULATOR_CHARGER_IDS: str = "charger-sim-1,charger-sim-2"
    SIMULATOR_FEATURES: str = "sine,cosine,random"
    SIMULATOR_TOPIC_TEMPLATE: str = "charger/{charger_id}/live-telemetry/{feature}"
    SIMULATOR_PAYLOAD_CHARGER_KEY: str = "charger_id"
    SIMULATOR_PAYLOAD_TYPE_KEY: str = "telemetry_type"
    SIMULATOR_VALUE_MIN: float = 0.0
    SIMULATOR_VALUE_MAX: float = 100.0
    SIMULATOR_BLIP_PROBABILITY: float = 0.0025
    SIMULATOR_BLIP_MULTIPLIER_MIN: float = 1.8
    SIMULATOR_BLIP_MULTIPLIER_MAX: float = 2.6

    @property
    def config(self) -> SimulatorConfig:
        charger_ids = self.SIMULATOR_CHARGER_IDS.split(",")
        features = self.SIMULATOR_FEATURES.split(",")

        return SimulatorConfig(
            enabled=self.SIMULATOR_ENABLED,
            broker_host=self.SIMULATOR_BROKER_HOST,
            broker_port=self.SIMULATOR_BROKER_PORT,
            use_tls=self.SIMULATOR_USE_TLS,
            use_auth=self.SIMULATOR_USE_AUTH,
            username=self.SIMULATOR_USERNAME,
            api_key=self.SIMULATOR_API_KEY,
            client_id_prefix=self.SIMULATOR_CLIENT_ID_PREFIX,
            interval_seconds=self.SIMULATOR_INTERVAL_SECONDS,
            qos=self.SIMULATOR_QOS,
            charger_ids=charger_ids,
            features=features,
            topic_template=self.SIMULATOR_TOPIC_TEMPLATE,
            payload_charger_key=self.SIMULATOR_PAYLOAD_CHARGER_KEY,
            payload_type_key=self.SIMULATOR_PAYLOAD_TYPE_KEY,
            value_min=self.SIMULATOR_VALUE_MIN,
            value_max=self.SIMULATOR_VALUE_MAX,
            blip_probability=self.SIMULATOR_BLIP_PROBABILITY,
            blip_multiplier_min=self.SIMULATOR_BLIP_MULTIPLIER_MIN,
            blip_multiplier_max=self.SIMULATOR_BLIP_MULTIPLIER_MAX,
        )


@lru_cache(maxsize=1)
def get_simulator_settings() -> SimulatorSettings:
    """Return cached simulator settings."""
    return SimulatorSettings()
