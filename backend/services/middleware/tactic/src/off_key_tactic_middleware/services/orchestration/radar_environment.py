"""Build the validated environment and labels for a RADAR workload."""

import hashlib
import json
from datetime import UTC, datetime

from off_key_core.config.logs import logger
from off_key_core.models import ADAPTIVE_MODEL_FAMILY, STATIC_MODEL_FAMILY
from off_key_core.schemas.radar import RadarStartConfig

from ...config.config import get_radar_runtime_settings, get_tactic_settings
from ...models.catalog import validate_model_params

# Where the deployment keeps a service is not RADAR behavior: a monitor started
# before the forecast service existed keeps its fingerprint when it gets the URL.
# The database and the secrets are the pool's own, never part of a workload.
_FINGERPRINT_EXCLUDED_KEYS = {
    "SERVICE_ID",
    "RADAR_LIFECYCLE_VERSION",
    "FORECAST_API_URL",
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
    """The labels a monitor's workload row carries."""
    monitoring = json.loads(environment["RADAR_MONITORING_CONFIG"])
    return {
        "owner": "tactic_middleware",
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "purpose": "RADAR anomaly detection service",
        "env": get_radar_runtime_settings().ENVIRONMENT,
        "service_type": "radar",
        "managed_by": "tactic",
        "monitoring_strategy": monitoring["strategy"],
        "radar_model_type": monitoring["model_type"],
        "radar_config_fingerprint": build_radar_config_fingerprint(environment),
        "radar_image": radar_image,
        "radar_service_id": environment["SERVICE_ID"],
        "radar_lifecycle_version": environment.get("RADAR_LIFECYCLE_VERSION", "1"),
    }


def build_radar_environment(
    *,
    service_id: str,
    config: RadarStartConfig,
    validate_params: bool,
) -> dict[str, str]:
    """Compile validated service configuration into RADAR environment variables.

    ``validate_params`` checks the model parameters, with catalogue defaults
    filled in, against the detector catalogue. The environment still carries the
    pipeline's own parameters, because RADAR rejects a monitoring config that
    differs from the one it derives from the pipeline. A persisted launch was
    validated when it was saved, so rebuilding it skips the check.
    """
    monitoring = config.monitoring
    performance = config.performance_config
    defaults = get_tactic_settings().config.radar_defaults
    runtime = get_radar_runtime_settings()
    environment = {
        "SERVICE_ID": service_id,
        "ENVIRONMENT": runtime.ENVIRONMENT,
        # The accepted topics name the stored streams the monitor reads.
        "RADAR_SUBSCRIPTION_TOPICS": ",".join(config.mqtt_topics),
        "RADAR_MEMORY_LIMIT_MB": str(defaults.memory_limit_mb),
        "RADAR_CHECKPOINT_INTERVAL": str(defaults.checkpoint_interval),
        "RADAR_MAX_QUEUE_SIZE": str(defaults.max_queue_size),
        "RADAR_SENSOR_KEY_STRATEGY": str(performance.sensor_key_strategy),
        "RADAR_HOLD_INTERVALS": str(performance.hold_intervals),
        "RADAR_MINIMUM_HOLD_SECONDS": str(performance.minimum_hold_seconds),
        "RADAR_FUTURE_TOLERANCE_SECONDS": str(performance.future_tolerance_seconds),
        "RADAR_DB_WRITE_ENABLED": str(defaults.db_write_enabled).lower(),
        "RADAR_DB_BATCH_SIZE": str(defaults.db_batch_size),
        "RADAR_DB_BATCH_TIMEOUT": str(defaults.db_batch_timeout),
        "RADAR_HEALTH_CHECK_INTERVAL": str(defaults.health_check_interval),
        "RADAR_LOG_LEVEL": defaults.log_level,
    }
    forecast_api_url = get_tactic_settings().config.forecast_api_url
    if forecast_api_url:
        # Pretrained forecaster steps ask this service for their forecasts. Its
        # token is a secret of the RADAR pool, which its children inherit.
        environment["FORECAST_API_URL"] = forecast_api_url
    if validate_params:
        try:
            validate_model_params(
                monitoring.model_type,
                monitoring.model_params,
                family=(
                    ADAPTIVE_MODEL_FAMILY
                    if monitoring.strategy == "adaptive_stream"
                    else STATIC_MODEL_FAMILY
                ),
            )
        except ValueError as exc:
            logger.error(
                "Invalid model parameters for %s: %s", monitoring.model_type, exc
            )
            raise ValueError(f"Invalid model parameters: {exc}") from exc

    # The pipeline defines the monitoring; RADAR rejects any other copy.
    environment["RADAR_MONITORING_CONFIG"] = monitoring.model_dump_json()
    environment["RADAR_PIPELINE_CONFIG"] = config.pipeline.model_dump_json()
    if config.shadow:
        # Only a shadow run carries the key, so the environment of every other
        # monitor, and with it its configuration fingerprint, stays as it was.
        environment["RADAR_SHADOW"] = "true"
    if config.runtime_image is not None:
        environment["RADAR_RUNTIME_IMAGE"] = config.runtime_image
    return environment
