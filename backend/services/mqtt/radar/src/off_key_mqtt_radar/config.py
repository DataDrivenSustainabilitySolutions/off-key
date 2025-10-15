"""
Configuration for MQTT RADAR service
"""

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings
from typing import Dict, Any, List, Optional
from dotenv import find_dotenv, load_dotenv
from pathlib import Path
import os


def load_configuration(custom_config_file: Optional[str] = None):
    """Load configuration from environment and optional custom file"""
    # Load default ".env" file from upper project tree
    load_dotenv()

    # Load custom configuration file if specified
    if custom_config_file:
        config_path = Path(custom_config_file)
        if config_path.exists():
            load_dotenv(config_path, override=True)
            return str(config_path.resolve())

    # Override with dev.env values if present
    dev_env = find_dotenv("dev.env")
    if dev_env:
        load_dotenv(dev_env, override=True)
        return dev_env

    return None


# Check for custom config file from environment variable
RADAR_CONFIG_FILE = os.getenv("RADAR_CONFIG_FILE")
loaded_config_file = load_configuration(RADAR_CONFIG_FILE)


class AnomalyDetectionConfig(BaseModel):
    """Configuration for anomaly detection models"""

    model_type: str = "isolation_forest"  # isolation_forest, adaptive_svm, knn
    model_params: Dict[str, Any] = {"num_trees": 100, "window_size": 2000}

    preprocessing_steps: List[Dict[str, Any]] = [
        {"type": "scaler", "params": {}},
        {"type": "pca", "params": {"n_components": 10}},
    ]

    thresholds: Dict[str, float] = {"medium": 0.6, "high": 0.8, "critical": 0.9}

    memory_limit_mb: int = 1000
    checkpoint_interval: int = 10000

    # Batch processing
    batch_size: int = 100
    batch_timeout: float = 1.0

    # Memory management
    reset_threshold_mb: int = 500


class MQTTRadarConfig(BaseModel):
    """MQTT RADAR service configuration"""

    # MQTT Connection
    broker_host: str = "localhost"
    broker_port: int = 1883
    use_tls: bool = False
    client_id_prefix: str = "radar"

    # Authentication (optional)
    use_auth: bool = False
    username: str = ""
    api_key: str = ""

    # Subscription settings
    subscription_topics: List[str] = [
        "charger/+/telemetry"
    ]  # Subscribe to telemetry from bridge
    subscription_qos: int = 0

    # Database settings
    db_write_enabled: bool = True
    db_batch_size: int = 50
    db_batch_timeout: float = 2.0

    # Monitoring
    health_check_interval: float = 30.0
    log_level: str = "INFO"

    # Performance
    worker_threads: int = 4
    max_queue_size: int = 10000

    # Security
    rate_limit_per_minute: int = 1000
    max_feature_count: int = 100
    max_string_length: int = 1000

    # Memory Management
    memory_limit_mb: int = 1000

    # Anomaly Detection
    model_type: str = "isolation_forest"
    thresholds: Dict[str, float] = {"medium": 0.6, "high": 0.8, "critical": 0.9}
    batch_size: int = 100
    batch_timeout: float = 1.0
    checkpoint_interval: int = 10000


class RadarSettings(BaseSettings):
    """Environment-based settings for RADAR service"""

    # Configuration Management
    custom_config_file: Optional[str] = None  # Path to custom config file being watched

    # MQTT Configuration
    RADAR_MQTT_BROKER_HOST: str = "localhost"
    RADAR_MQTT_BROKER_PORT: int = 1883
    RADAR_MQTT_USE_TLS: bool = False
    RADAR_MQTT_CLIENT_ID_PREFIX: str = "radar"

    # Authentication
    RADAR_MQTT_USE_AUTH: bool = False
    RADAR_MQTT_USERNAME: str = ""
    RADAR_MQTT_API_KEY: str = ""

    # Topics
    RADAR_SUBSCRIPTION_TOPICS: str = "charger/+/telemetry"  # Comma-separated
    RADAR_SUBSCRIPTION_QOS: int = 0

    # Database
    RADAR_DB_WRITE_ENABLED: bool = True
    RADAR_DB_BATCH_SIZE: int = 50
    RADAR_DB_BATCH_TIMEOUT: float = 2.0

    # Anomaly Detection
    RADAR_MODEL_TYPE: str = "isolation_forest"
    RADAR_ANOMALY_THRESHOLD_MEDIUM: float = 0.6
    RADAR_ANOMALY_THRESHOLD_HIGH: float = 0.8
    RADAR_ANOMALY_THRESHOLD_CRITICAL: float = 0.9

    # Performance
    RADAR_BATCH_SIZE: int = 100
    RADAR_BATCH_TIMEOUT: float = 1.0
    RADAR_MEMORY_LIMIT_MB: int = 1000
    RADAR_CHECKPOINT_INTERVAL: int = 10000

    # Monitoring
    RADAR_HEALTH_CHECK_INTERVAL: float = 30.0
    RADAR_LOG_LEVEL: str = "INFO"
    RADAR_RATE_LIMIT_PER_MINUTE: int = 1000

    class Config:
        env_file = ".env"
        case_sensitive = True

    @field_validator("RADAR_SUBSCRIPTION_TOPICS")
    @classmethod
    def validate_topics(cls, v: str) -> str:
        """Validate subscription topics format"""
        if not v:
            raise ValueError("At least one subscription topic is required")
        return v

    @property
    def config(self) -> MQTTRadarConfig:
        """Create MQTTRadarConfig from environment settings"""

        # Parse topics
        topics = [topic.strip() for topic in self.RADAR_SUBSCRIPTION_TOPICS.split(",")]

        return MQTTRadarConfig(
            broker_host=self.RADAR_MQTT_BROKER_HOST,
            broker_port=self.RADAR_MQTT_BROKER_PORT,
            use_tls=self.RADAR_MQTT_USE_TLS,
            client_id_prefix=self.RADAR_MQTT_CLIENT_ID_PREFIX,
            use_auth=self.RADAR_MQTT_USE_AUTH,
            username=self.RADAR_MQTT_USERNAME,
            api_key=self.RADAR_MQTT_API_KEY,
            subscription_topics=topics,
            subscription_qos=self.RADAR_SUBSCRIPTION_QOS,
            db_write_enabled=self.RADAR_DB_WRITE_ENABLED,
            db_batch_size=self.RADAR_DB_BATCH_SIZE,
            db_batch_timeout=self.RADAR_DB_BATCH_TIMEOUT,
            health_check_interval=self.RADAR_HEALTH_CHECK_INTERVAL,
            log_level=self.RADAR_LOG_LEVEL,
            rate_limit_per_minute=self.RADAR_RATE_LIMIT_PER_MINUTE,
            memory_limit_mb=self.RADAR_MEMORY_LIMIT_MB,
            model_type=self.RADAR_MODEL_TYPE,
            thresholds={
                "medium": self.RADAR_ANOMALY_THRESHOLD_MEDIUM,
                "high": self.RADAR_ANOMALY_THRESHOLD_HIGH,
                "critical": self.RADAR_ANOMALY_THRESHOLD_CRITICAL,
            },
            batch_size=self.RADAR_BATCH_SIZE,
            batch_timeout=self.RADAR_BATCH_TIMEOUT,
            checkpoint_interval=self.RADAR_CHECKPOINT_INTERVAL,
        )


# Global settings instance
radar_settings = RadarSettings()

# Store the loaded config file path for the file watcher
radar_settings.custom_config_file = loaded_config_file
