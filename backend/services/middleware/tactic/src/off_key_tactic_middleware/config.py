"""
TACTIC Middleware Configuration

Configuration for the TACTIC
(Timely Anomaly Communication / Task Instance Control) service
including Docker API configuration,
RADAR orchestration settings, and service-specific parameters.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Self, Optional
from dotenv import find_dotenv, load_dotenv

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class DockerConfig(BaseModel):
    """
    Docker API configuration for container orchestration.
    """

    # Docker API Connection
    api_url: str = "http://socket-proxy"
    api_port: int = 2375
    max_concurrent_calls: int = 5

    # Container Defaults
    default_network: str = "emqx-network"
    default_restart_policy: str = "on-failure"
    default_restart_max_attempts: int = 3

    # Resource Limits
    default_memory_limit: str = "512m"
    default_cpu_limit: str = "0.5"
    default_constraints: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"
        validate_assignment = True

    @field_validator("api_port")
    @classmethod
    def validate_api_port(cls, v: int) -> int:
        """Validate Docker API port is in valid range"""
        if not 1 <= v <= 65535:
            raise ValueError("Docker API port must be between 1 and 65535")
        return v

    @field_validator("max_concurrent_calls")
    @classmethod
    def validate_max_concurrent_calls(cls, v: int) -> int:
        """Validate max concurrent calls is reasonable"""
        if not 1 <= v <= 100:
            raise ValueError("Max concurrent calls must be between 1 and 100")
        return v

    @field_validator("default_restart_max_attempts")
    @classmethod
    def validate_restart_max_attempts(cls, v: int) -> int:
        """Validate restart max attempts"""
        if not 0 <= v <= 10:
            raise ValueError("Restart max attempts must be between 0 and 10")
        return v

    @property
    def base_url(self) -> str:
        """Get Docker API base URL"""
        return f"{self.api_url}:{self.api_port}"


class RadarDefaultsConfig(BaseModel):
    """
    Default configuration values for RADAR services.
    """

    # Default MQTT Settings
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_use_tls: bool = False
    mqtt_client_id_prefix: str = "radar"
    mqtt_use_auth: bool = False
    mqtt_qos: int = 0

    # Default Model Settings
    model_type: str = "isolation_forest"

    # Default Anomaly Thresholds
    anomaly_threshold_medium: float = 0.6
    anomaly_threshold_high: float = 0.8
    anomaly_threshold_critical: float = 0.9

    # Default Performance Settings
    batch_size: int = 100
    batch_timeout: float = 1.0
    memory_limit_mb: int = 1000
    checkpoint_interval: int = 10000

    # Default Database Settings
    db_write_enabled: bool = True
    db_batch_size: int = 50
    db_batch_timeout: float = 2.0

    # Default Health Settings
    health_check_interval: float = 30.0
    log_level: str = "INFO"
    rate_limit_per_minute: int = 1000

    class Config:
        extra = "forbid"
        validate_assignment = True

    @field_validator("mqtt_broker_port")
    @classmethod
    def validate_mqtt_port(cls, v: int) -> int:
        """Validate MQTT broker port"""
        if not 1 <= v <= 65535:
            raise ValueError("MQTT broker port must be between 1 and 65535")
        return v

    @field_validator("mqtt_qos")
    @classmethod
    def validate_mqtt_qos(cls, v: int) -> int:
        """Validate MQTT QoS level"""
        if v not in [0, 1, 2]:
            raise ValueError("MQTT QoS must be 0, 1, or 2")
        return v

    @field_validator("model_type")
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        """Validate ML model type"""
        valid_models = ["isolation_forest", "adaptive_svm", "knn"]
        if v not in valid_models:
            raise ValueError(f"Model type must be one of: {valid_models}")
        return v

    @field_validator(
        "anomaly_threshold_medium",
        "anomaly_threshold_high",
        "anomaly_threshold_critical",
    )
    @classmethod
    def validate_anomaly_threshold(cls, v: float) -> float:
        """Validate anomaly threshold is between 0 and 1"""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Anomaly threshold must be between 0.0 and 1.0")
        return v

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Validate batch size"""
        if not 1 <= v <= 10000:
            raise ValueError("Batch size must be between 1 and 10000")
        return v

    @field_validator("batch_timeout", "db_batch_timeout", "health_check_interval")
    @classmethod
    def validate_timeout(cls, v: float) -> float:
        """Validate timeout values"""
        if not 0.1 <= v <= 3600.0:
            raise ValueError("Timeout must be between 0.1 and 3600.0 seconds")
        return v

    @field_validator("memory_limit_mb")
    @classmethod
    def validate_memory_limit(cls, v: int) -> int:
        """Validate memory limit"""
        if not 128 <= v <= 16384:
            raise ValueError("Memory limit must be between 128 and 16384 MB")
        return v

    @field_validator("checkpoint_interval")
    @classmethod
    def validate_checkpoint_interval(cls, v: int) -> int:
        """Validate checkpoint interval"""
        if not 100 <= v <= 100000:
            raise ValueError("Checkpoint interval must be between 100 and 100000")
        return v

    @field_validator("db_batch_size")
    @classmethod
    def validate_db_batch_size(cls, v: int) -> int:
        """Validate database batch size"""
        if not 1 <= v <= 1000:
            raise ValueError("Database batch size must be between 1 and 1000")
        return v

    @field_validator("rate_limit_per_minute")
    @classmethod
    def validate_rate_limit(cls, v: int) -> int:
        """Validate rate limit per minute"""
        if not 1 <= v <= 100000:
            raise ValueError("Rate limit per minute must be between 1 and 100000")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> Self:
        """Validate that anomaly thresholds are in correct order"""
        if not (
            self.anomaly_threshold_medium
            <= self.anomaly_threshold_high
            <= self.anomaly_threshold_critical
        ):
            raise ValueError(
                "Anomaly thresholds must be ordered: medium <= high <= critical "
                f"(got {self.anomaly_threshold_medium} "
                f"<= {self.anomaly_threshold_high} "
                f"<= {self.anomaly_threshold_critical})"
            )
        return self


class TacticConfig(BaseModel):
    """
    Complete TACTIC service configuration with business logic validation.
    """

    # Service Information
    service_name: str = "tactic-middleware"
    service_version: str = "0.1.0"

    # API Configuration
    host: str = "0.0.0.0"
    port: int = 8000

    # Docker Configuration
    docker: DockerConfig

    # RADAR Defaults
    radar_defaults: RadarDefaultsConfig

    # Database Configuration
    database_url: Optional[str] = None

    # Logging Configuration
    log_level: str = "INFO"

    class Config:
        extra = "forbid"
        validate_assignment = True

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate service port"""
        if not 1 <= v <= 65535:
            raise ValueError("Service port must be between 1 and 65535")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


class TacticSettings(BaseSettings):
    """Environment-based settings for TACTIC service"""

    # Service Configuration
    TACTIC_SERVICE_NAME: str = "tactic-middleware"
    TACTIC_SERVICE_VERSION: str = "0.1.0"
    TACTIC_HOST: str = "0.0.0.0"
    TACTIC_PORT: int = 8000
    TACTIC_LOG_LEVEL: str = "INFO"

    # Docker API Configuration
    TACTIC_DOCKER_API_URL: str = "http://socket-proxy"
    TACTIC_DOCKER_API_PORT: int = 2375
    TACTIC_DOCKER_MAX_CONCURRENT_CALLS: int = 5
    TACTIC_DOCKER_DEFAULT_NETWORK: str = "emqx-network"
    TACTIC_DOCKER_DEFAULT_RESTART_POLICY: str = "on-failure"
    TACTIC_DOCKER_DEFAULT_RESTART_MAX_ATTEMPTS: int = 3
    TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT: str = "512m"
    TACTIC_DOCKER_DEFAULT_CPU_LIMIT: str = "0.5"
    TACTIC_DOCKER_DEFAULT_CONSTRAINTS: str = "node.role == worker"

    # RADAR Default Configuration
    TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST: str = "localhost"
    TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT: int = 1883
    TACTIC_RADAR_DEFAULT_MQTT_USE_TLS: bool = False
    TACTIC_RADAR_DEFAULT_MQTT_CLIENT_ID_PREFIX: str = "radar"
    TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH: bool = False
    TACTIC_RADAR_DEFAULT_MQTT_QOS: int = 0
    TACTIC_RADAR_DEFAULT_MODEL_TYPE: str = "isolation_forest"
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_MEDIUM: float = 0.6
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_HIGH: float = 0.8
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_CRITICAL: float = 0.9
    TACTIC_RADAR_DEFAULT_BATCH_SIZE: int = 100
    TACTIC_RADAR_DEFAULT_BATCH_TIMEOUT: float = 1.0
    TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB: int = 1000
    TACTIC_RADAR_DEFAULT_CHECKPOINT_INTERVAL: int = 10000
    TACTIC_RADAR_DEFAULT_DB_WRITE_ENABLED: bool = True
    TACTIC_RADAR_DEFAULT_DB_BATCH_SIZE: int = 50
    TACTIC_RADAR_DEFAULT_DB_BATCH_TIMEOUT: float = 2.0
    TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL: float = 30.0
    TACTIC_RADAR_DEFAULT_LOG_LEVEL: str = "INFO"
    TACTIC_RADAR_DEFAULT_RATE_LIMIT_PER_MINUTE: int = 1000

    # Database Configuration
    TACTIC_DATABASE_URL: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

    @staticmethod
    def _split_constraints(raw_value: str) -> list[str]:
        if not raw_value:
            return []
        values: list[str] = []
        for item in raw_value.split(","):
            cleaned = item.strip()
            if not cleaned:
                continue
            if cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
                cleaned = cleaned[1:-1].strip()
            if cleaned:
                values.append(cleaned)
        return values

    def _parse_default_constraints(self) -> list[str]:
        return self._split_constraints(self.TACTIC_DOCKER_DEFAULT_CONSTRAINTS)

    @property
    def config(self) -> TacticConfig:
        """
        Create TacticConfig instance from environment settings.

        Returns:
            TacticConfig: Validated TACTIC service configuration
        """
        docker_config = DockerConfig(
            api_url=self.TACTIC_DOCKER_API_URL,
            api_port=self.TACTIC_DOCKER_API_PORT,
            max_concurrent_calls=self.TACTIC_DOCKER_MAX_CONCURRENT_CALLS,
            default_network=self.TACTIC_DOCKER_DEFAULT_NETWORK,
            default_restart_policy=self.TACTIC_DOCKER_DEFAULT_RESTART_POLICY,
            default_restart_max_attempts=self.TACTIC_DOCKER_DEFAULT_RESTART_MAX_ATTEMPTS,
            default_memory_limit=self.TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT,
            default_cpu_limit=self.TACTIC_DOCKER_DEFAULT_CPU_LIMIT,
            default_constraints=self._parse_default_constraints(),
        )

        radar_defaults_config = RadarDefaultsConfig(
            mqtt_broker_host=self.TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST,
            mqtt_broker_port=self.TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT,
            mqtt_use_tls=self.TACTIC_RADAR_DEFAULT_MQTT_USE_TLS,
            mqtt_client_id_prefix=self.TACTIC_RADAR_DEFAULT_MQTT_CLIENT_ID_PREFIX,
            mqtt_use_auth=self.TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH,
            mqtt_qos=self.TACTIC_RADAR_DEFAULT_MQTT_QOS,
            model_type=self.TACTIC_RADAR_DEFAULT_MODEL_TYPE,
            anomaly_threshold_medium=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_MEDIUM,
            anomaly_threshold_high=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_HIGH,
            anomaly_threshold_critical=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_CRITICAL,
            batch_size=self.TACTIC_RADAR_DEFAULT_BATCH_SIZE,
            batch_timeout=self.TACTIC_RADAR_DEFAULT_BATCH_TIMEOUT,
            memory_limit_mb=self.TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB,
            checkpoint_interval=self.TACTIC_RADAR_DEFAULT_CHECKPOINT_INTERVAL,
            db_write_enabled=self.TACTIC_RADAR_DEFAULT_DB_WRITE_ENABLED,
            db_batch_size=self.TACTIC_RADAR_DEFAULT_DB_BATCH_SIZE,
            db_batch_timeout=self.TACTIC_RADAR_DEFAULT_DB_BATCH_TIMEOUT,
            health_check_interval=self.TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL,
            log_level=self.TACTIC_RADAR_DEFAULT_LOG_LEVEL,
            rate_limit_per_minute=self.TACTIC_RADAR_DEFAULT_RATE_LIMIT_PER_MINUTE,
        )

        return TacticConfig(
            service_name=self.TACTIC_SERVICE_NAME,
            service_version=self.TACTIC_SERVICE_VERSION,
            host=self.TACTIC_HOST,
            port=self.TACTIC_PORT,
            docker=docker_config,
            radar_defaults=radar_defaults_config,
            database_url=self.TACTIC_DATABASE_URL,
            log_level=self.TACTIC_LOG_LEVEL,
        )


# Global settings instance
tactic_settings = TacticSettings()
