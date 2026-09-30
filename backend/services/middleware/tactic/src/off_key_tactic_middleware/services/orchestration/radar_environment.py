"""Build the validated environment and labels for a RADAR workload."""

import hashlib
import json
from datetime import UTC, datetime

from off_key_core.config.logs import logger
from off_key_core.models import ADAPTIVE_MODEL_FAMILY, STATIC_MODEL_FAMILY
from off_key_core.schemas.radar import RadarStartConfig

from ...config.config import (
    get_radar_container_runtime_settings,
    get_tactic_settings,
)
from ...models.registry import ModelRegistryService

_FINGERPRINT_EXCLUDED_KEYS = {
    "SERVICE_ID",
    "RADAR_DATABASE_URL",
}


def build_radar_config_fingerprint(environment: dict[str, str]) -> str:
    """Return a stable fingerprint of settings that define RADAR behavior."""
    comparable_environment = {
        key: value
        for key, value in environment.items()
        if key not in _FINGERPRINT_EXCLUDED_KEYS
    }
    serialized = json.dumps(
        comparable_environment,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def build_radar_workload_labels(
    environment: dict[str, str], radar_image: str
) -> dict[str, str]:
    """Build the canonical labels shared by Swarm and container workloads."""
    monitoring = json.loads(environment["RADAR_MONITORING_CONFIG"])
    return {
        "owner": "tactic_middleware",
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "purpose": "RADAR anomaly detection service",
        "env": get_radar_container_runtime_settings().ENVIRONMENT,
        "service_type": "radar",
        "managed_by": "tactic",
        "monitoring_strategy": monitoring["strategy"],
        "radar_model_type": monitoring["model_type"],
        "radar_config_fingerprint": build_radar_config_fingerprint(environment),
        "radar_image": radar_image,
    }


def build_radar_environment(
    *,
    service_id: str,
    config: RadarStartConfig,
    model_registry: ModelRegistryService,
) -> dict[str, str]:
    """Compile validated service configuration into RADAR environment variables."""
    monitoring = config.monitoring
    mqtt_config = config.mqtt_config
    performance = config.performance_config
    defaults = get_tactic_settings().config.radar_defaults
    runtime = get_radar_container_runtime_settings()
    if runtime.ENVIRONMENT == "production":
        forbidden = {
            "host",
            "port",
            "use_tls",
            "use_auth",
            "username",
            "api_key",
        } & mqtt_config.keys()
        if forbidden:
            raise ValueError("Production MQTT connection settings cannot be overridden")
    environment = {
        "SERVICE_ID": service_id,
        "ENVIRONMENT": runtime.ENVIRONMENT,
        "RADAR_MQTT_BROKER_HOST": mqtt_config.get("host", defaults.mqtt_broker_host),
        "RADAR_MQTT_BROKER_PORT": str(
            mqtt_config.get("port", defaults.mqtt_broker_port)
        ),
        "RADAR_MQTT_USE_TLS": str(
            mqtt_config.get("use_tls", defaults.mqtt_use_tls)
        ).lower(),
        "RADAR_MQTT_CLIENT_ID_PREFIX": mqtt_config.get(
            "client_id_prefix", defaults.mqtt_client_id_prefix
        ),
        "RADAR_MQTT_USE_AUTH": str(
            mqtt_config.get("use_auth", defaults.mqtt_use_auth)
        ).lower(),
        "RADAR_MQTT_USERNAME": mqtt_config.get("username", defaults.mqtt_username),
        "RADAR_SUBSCRIPTION_TOPICS": ",".join(config.mqtt_topics),
        "RADAR_SUBSCRIPTION_QOS": str(mqtt_config.get("qos", defaults.mqtt_qos)),
        "RADAR_BATCH_SIZE": str(
            defaults.batch_size
        ),
        "RADAR_BATCH_TIMEOUT": str(
            defaults.batch_timeout
        ),
        "RADAR_MEMORY_LIMIT_MB": str(
            defaults.memory_limit_mb
        ),
        "RADAR_CHECKPOINT_INTERVAL": str(
            defaults.checkpoint_interval
        ),
        "RADAR_SENSOR_KEY_STRATEGY": str(
            performance.sensor_key_strategy
        ),
        "RADAR_SENSOR_FRESHNESS_SECONDS": str(
            performance.sensor_freshness_seconds
        ),
        "RADAR_DB_WRITE_ENABLED": str(
            defaults.db_write_enabled
        ).lower(),
        "RADAR_DB_BATCH_SIZE": str(
            defaults.db_batch_size
        ),
        "RADAR_DB_BATCH_TIMEOUT": str(
            defaults.db_batch_timeout
        ),
        "RADAR_DATABASE_URL": runtime.radar_database_url,
        "RADAR_HEALTH_CHECK_INTERVAL": str(
            defaults.health_check_interval
        ),
        "RADAR_LOG_LEVEL": defaults.log_level,
        "RADAR_RATE_LIMIT_PER_MINUTE": str(
            defaults.rate_limit_per_minute
        ),
    }
    if runtime.ENVIRONMENT == "production":
        environment["RADAR_MQTT_CA_FILE"] = "/run/secrets/EMQX_CA_CERT"
    elif mqtt_config.get("api_key"):
        environment["RADAR_MQTT_API_KEY"] = mqtt_config["api_key"]

    try:
        validated_params = model_registry.validate_model_params(
            monitoring.model_type,
            monitoring.model_params,
            category="model",
            family=(
                ADAPTIVE_MODEL_FAMILY
                if monitoring.strategy == "adaptive_stream"
                else STATIC_MODEL_FAMILY
            ),
        )
    except ValueError as exc:
        logger.error("Invalid model parameters for %s: %s", monitoring.model_type, exc)
        raise ValueError(f"Invalid model parameters: {exc}") from exc

    monitoring = monitoring.model_copy(update={"model_params": validated_params})
    environment["RADAR_MONITORING_CONFIG"] = monitoring.model_dump_json()
    logger.info("Model params validated for %s: %s", monitoring.model_type, validated_params)
    return environment
