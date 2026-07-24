"""Build the validated environment and labels for a RADAR workload."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from off_key_core.config.logs import logger
from off_key_core.schemas.radar import StaticBaselineConfig

from ...config.config import (
    get_radar_container_runtime_settings,
    get_tactic_settings,
)
from ...models.registry import ModelRegistryService

_FINGERPRINT_EXCLUDED_KEYS = {
    "SERVICE_ID",
    "RADAR_DATABASE_URL",
    "RADAR_TACTIC_SERVICE_HOST",
    "RADAR_TACTIC_SERVICE_PORT",
    "RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS",
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
    return {
        "owner": "tactic_middleware",
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "purpose": "RADAR anomaly detection service",
        "env": get_radar_container_runtime_settings().ENVIRONMENT,
        "service_type": "radar",
        "managed_by": "tactic",
        "monitoring_strategy": environment.get(
            "RADAR_MONITORING_STRATEGY", "static_baseline"
        ),
        "radar_model_type": environment.get("RADAR_MODEL_TYPE", ""),
        "radar_config_fingerprint": build_radar_config_fingerprint(environment),
        "radar_image": radar_image,
    }


def build_radar_environment(
    *,
    service_id: str,
    mqtt_topics: list[str],
    strategy: str,
    model_type: str,
    model_params: dict[str, Any],
    mqtt_config: dict[str, Any],
    performance_config: dict[str, Any],
    static_baseline_config: dict[str, Any],
    model_registry: ModelRegistryService,
) -> dict[str, str]:
    """Compile validated service configuration into RADAR environment variables."""
    strategy = (strategy or "static_baseline").strip().lower()
    if strategy != "static_baseline":
        raise ValueError(
            "Invalid monitoring strategy. Only static_baseline can be started; "
            "dynamic monitoring is not implemented."
        )

    defaults = get_tactic_settings().config.radar_defaults
    runtime = get_radar_container_runtime_settings()
    static_config = StaticBaselineConfig(
        **{
            **static_baseline_config,
            "model_type": static_baseline_config.get(
                "model_type", model_type or "pyod_iforest"
            ),
            "model_params": static_baseline_config.get(
                "model_params", model_params or {}
            ),
        }
    )
    model_type = static_config.model_type
    model_params = static_config.model_params
    normalized_static_config = static_config.model_dump(exclude_none=True)

    environment = {
        "SERVICE_ID": service_id,
        "RADAR_MONITORING_STRATEGY": strategy,
        "RADAR_TACTIC_SERVICE_HOST": runtime.TACTIC_SERVICE_HOST,
        "RADAR_TACTIC_SERVICE_PORT": str(runtime.TACTIC_SERVICE_PORT),
        "RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS": str(
            runtime.TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS
        ),
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
        "RADAR_MQTT_USERNAME": mqtt_config.get("username", ""),
        "RADAR_MQTT_API_KEY": mqtt_config.get("api_key", ""),
        "RADAR_SUBSCRIPTION_TOPICS": ",".join(mqtt_topics),
        "RADAR_SUBSCRIPTION_QOS": str(mqtt_config.get("qos", defaults.mqtt_qos)),
        "RADAR_MODEL_TYPE": model_type or defaults.model_type,
        "RADAR_STATIC_BASELINE_CONFIG": json.dumps(normalized_static_config),
        "RADAR_BATCH_SIZE": str(
            performance_config.get("batch_size", defaults.batch_size)
        ),
        "RADAR_BATCH_TIMEOUT": str(
            performance_config.get("batch_timeout", defaults.batch_timeout)
        ),
        "RADAR_MEMORY_LIMIT_MB": str(
            performance_config.get("memory_limit_mb", defaults.memory_limit_mb)
        ),
        "RADAR_CHECKPOINT_INTERVAL": str(
            performance_config.get("checkpoint_interval", defaults.checkpoint_interval)
        ),
        "RADAR_SENSOR_KEY_STRATEGY": str(
            performance_config.get("sensor_key_strategy", defaults.sensor_key_strategy)
        ),
        "RADAR_ALIGNMENT_MODE": str(
            performance_config.get("alignment_mode", defaults.alignment_mode)
        ),
        "RADAR_SENSOR_FRESHNESS_SECONDS": str(
            performance_config.get(
                "sensor_freshness_seconds", defaults.sensor_freshness_seconds
            )
        ),
        "RADAR_DB_WRITE_ENABLED": str(
            performance_config.get("db_write_enabled", defaults.db_write_enabled)
        ).lower(),
        "RADAR_DB_BATCH_SIZE": str(
            performance_config.get("db_batch_size", defaults.db_batch_size)
        ),
        "RADAR_DB_BATCH_TIMEOUT": str(
            performance_config.get("db_batch_timeout", defaults.db_batch_timeout)
        ),
        "RADAR_DATABASE_URL": runtime.radar_database_url,
        "RADAR_HEALTH_CHECK_INTERVAL": str(
            performance_config.get(
                "health_check_interval", defaults.health_check_interval
            )
        ),
        "RADAR_LOG_LEVEL": performance_config.get("log_level", defaults.log_level),
        "RADAR_RATE_LIMIT_PER_MINUTE": str(
            performance_config.get(
                "rate_limit_per_minute", defaults.rate_limit_per_minute
            )
        ),
    }

    try:
        validated_params = model_registry.validate_model_params(
            model_type, model_params, category="model"
        )
    except ValueError as exc:
        logger.error("Invalid model parameters for %s: %s", model_type, exc)
        raise ValueError(f"Invalid model parameters: {exc}") from exc

    environment["RADAR_MODEL_PARAMS"] = json.dumps(validated_params)
    normalized_static_config["model_params"] = validated_params
    environment["RADAR_STATIC_BASELINE_CONFIG"] = json.dumps(normalized_static_config)
    logger.info("Model params validated for %s: %s", model_type, validated_params)
    return environment
