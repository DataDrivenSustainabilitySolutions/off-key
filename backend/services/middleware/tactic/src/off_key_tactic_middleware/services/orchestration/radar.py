import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional

import docker
from docker.types import RestartPolicy, ServiceMode, Resources
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.radar import (
    AdaptiveStreamConfig,
    PerformanceConfig,
    StaticBaselineConfig,
)
from off_key_core.utils.mqtt_topics import normalize_mqtt_topic_filters
from ...models.registry import ModelRegistryService
from ...facades.docker import AsyncDocker, get_workload_docker_status
from ...config.config import (
    get_radar_container_runtime_settings,
    get_tactic_settings,
)

MANAGED_BY_TACTIC_LABEL = "managed_by=tactic"
RADAR_SERVICE_TYPE_LABEL = "service_type=radar"

# Swarm manager status is stable over short windows: cache the result to avoid
# a docker.info() round-trip on every RADAR service creation request.
_SWARM_CACHE_TTL_SECONDS: float = 30.0
_swarm_manager_cache: Optional[tuple[bool, float]] = None


def _extract_adaptive_performance_config(values: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only fields owned by the shared adaptive performance schema."""
    if not values:
        return {}
    return {
        field_name: values[field_name]
        for field_name in PerformanceConfig.model_fields
        if field_name in values
    }


@lru_cache(maxsize=1)
def get_async_docker() -> AsyncDocker:
    """Create Docker facade lazily to avoid import-time settings evaluation.

    Note:
        This function is cached. Tests that monkeypatch Docker behavior or related
        settings should clear the cache between cases.
    """
    return AsyncDocker()


def reset_async_docker_cache_for_tests() -> None:
    """Clear cached AsyncDocker singleton for deterministic tests/tooling."""
    get_async_docker.cache_clear()


def _parse_memory_string(memory_str: str) -> int:
    """
    Convert memory string (e.g., '512m', '1g', '1024') to bytes.

    Args:
        memory_str: Memory string with optional suffix (k, m, g)

    Returns:
        int: Memory in bytes
    """
    if not memory_str:
        return 536870912  # Default 512MB in bytes

    memory_str = memory_str.lower().strip()

    # If it's already a number, assume bytes
    if memory_str.isdigit():
        return int(memory_str)

    # Parse with suffixes
    multipliers = {
        "k": 1024,
        "m": 1024 * 1024,
        "g": 1024 * 1024 * 1024,
        "kb": 1024,
        "mb": 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
    }

    for suffix, multiplier in multipliers.items():
        if memory_str.endswith(suffix):
            number_part = memory_str[: -len(suffix)].strip()
            try:
                return int(float(number_part) * multiplier)
            except ValueError:
                logger.warning(
                    f"Invalid memory format: {memory_str}, using default 512MB"
                )
                return 536870912

    logger.warning(f"Unknown memory format: {memory_str}, using default 512MB")
    return 536870912


class RadarOrchestrationService:
    """
    Service responsible for orchestrating RADAR
    (MQTT Real-Time Anomaly Detector) containers.

    This service handles:
    - Creating RADAR containers with specific model and parameters
    - Managing RADAR service lifecycle (start, stop, status)
    - Parsing and applying environment variables from RADAR configuration
    """

    def __init__(self, session: AsyncSession, model_registry: ModelRegistryService):
        self.session: AsyncSession = session
        self.async_docker: AsyncDocker = get_async_docker()
        self.model_registry = model_registry
        logger.info("RadarOrchestrationService initialized.")

    async def create_radar_service(
        self,
        container_name: str,
        mqtt_topics: List[str],
        strategy: str = "adaptive_stream",
        model_type: str = "isolation_forest",
        model_params: Optional[Dict[str, Any]] = None,
        preprocessing_steps: Optional[List[Dict[str, Any]]] = None,
        mqtt_config: Optional[Dict[str, Any]] = None,
        anomaly_thresholds: Optional[Dict[str, float]] = None,
        performance_config: Optional[Dict[str, Any]] = None,
        static_baseline_config: Optional[Dict[str, Any]] = None,
        adaptive_stream_config: Optional[Dict[str, Any]] = None,
    ) -> MonitoringService:
        """
        Create and start a RADAR Docker service for anomaly detection.

        Args:
            container_name (str): Name for the Docker container
            mqtt_topics (List[str]): List of MQTT topics to monitor
            strategy (str): Monitoring strategy selected by the user
            model_type (str): Type of ML model (isolation_forest, adaptive_svm, knn)
            model_params (Dict, optional): Model-specific parameters
            preprocessing_steps (List[Dict], optional): Preprocessing pipeline steps
            mqtt_config (Dict, optional): MQTT connection configuration
            anomaly_thresholds (Dict, optional): Anomaly detection thresholds
            performance_config (Dict, optional): Performance and resource settings
            static_baseline_config (Dict, optional): Static conformal settings
            adaptive_stream_config (Dict, optional): Adaptive stream settings

        Returns:
            MonitoringService: The created monitoring service database entry
        """
        mqtt_topics = normalize_mqtt_topic_filters(
            mqtt_topics,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )
        strategy = (strategy or "adaptive_stream").strip().lower()
        db_service_id = str(uuid.uuid4())
        env_vars = self._build_radar_environment(
            service_id=db_service_id,
            mqtt_topics=mqtt_topics,
            strategy=strategy,
            model_type=model_type,
            model_params=model_params or {},
            preprocessing_steps=preprocessing_steps or [],
            mqtt_config=mqtt_config or {},
            anomaly_thresholds=anomaly_thresholds or {},
            performance_config=performance_config or {},
            static_baseline_config=static_baseline_config or {},
            adaptive_stream_config=adaptive_stream_config or {},
        )
        config_fingerprint = self._build_radar_config_fingerprint(env_vars)

        # Check if service with this name already exists
        query = select(MonitoringService).where(
            MonitoringService.container_name == container_name
        )
        result = await self.session.execute(query)
        existing_service = result.scalars().first()

        if existing_service:
            return await self._resolve_existing_service_request(
                existing_service=existing_service,
                container_name=container_name,
                mqtt_topics=mqtt_topics,
                strategy=strategy,
                model_type=env_vars.get("RADAR_MODEL_TYPE", ""),
                config_fingerprint=config_fingerprint,
            )

        # Create the RADAR workload (Swarm service when available, otherwise container)
        docker_workload: Any = None
        try:
            docker_workload = await self._create_radar_workload(
                service_id=db_service_id,
                environment=env_vars,
            )
            await self._validate_radar_workload_started(docker_workload)

            # Create monitoring service record
            service_record = MonitoringService(
                id=db_service_id,
                container_id=docker_workload.id,
                container_name=container_name,
                mqtt_topic=mqtt_topics,
                created_at=datetime.now(),
                status=True,
            )

            # Add to database
            self.session.add(service_record)
            await self.session.commit()

            logger.info(f"RADAR workload created with ID: {docker_workload.id}")
            logger.info(f"RADAR service added to database with ID: {service_record.id}")

            return service_record

        except Exception as e:
            await self.session.rollback()
            if docker_workload is not None:
                await self._remove_created_workload_after_failure(docker_workload)
            logger.error(f"Failed to create RADAR service: {e}")
            raise

    async def _resolve_existing_service_request(
        self,
        *,
        existing_service: MonitoringService,
        container_name: str,
        mqtt_topics: List[str],
        strategy: str,
        model_type: str,
        config_fingerprint: str,
    ) -> MonitoringService:
        """Reject duplicate names unless the existing active workload matches."""
        if not existing_service.status:
            raise ValueError(
                f"RADAR service name '{container_name}' already exists as an "
                "inactive service. Use a unique container name."
            )

        docker_status = await self._get_docker_status(
            existing_service.container_id or ""
        )
        if docker_status != "running":
            existing_service.status = False
            await self.session.commit()
            raise ValueError(
                f"RADAR service name '{container_name}' is marked active, but its "
                f"Docker workload is not running (docker_status={docker_status}). "
                "The stale service was marked inactive; use a unique container name."
            )

        existing_topics = normalize_mqtt_topic_filters(
            existing_service.mqtt_topic,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )
        if existing_topics != mqtt_topics:
            raise ValueError(
                f"RADAR service name '{container_name}' already belongs to a "
                "running service with different MQTT topics."
            )

        labels = await self._get_workload_labels(existing_service.container_id or "")
        existing_fingerprint = labels.get("radar_config_fingerprint")
        if existing_fingerprint and existing_fingerprint != config_fingerprint:
            raise ValueError(
                f"RADAR service name '{container_name}' already belongs to a "
                "running service with a different RADAR configuration."
            )

        expected_labels = {
            "monitoring_strategy": strategy,
            "radar_model_type": (model_type or "").strip().lower(),
        }
        for label_key, expected_value in expected_labels.items():
            label_value = labels.get(label_key)
            if label_value and label_value.strip().lower() != expected_value:
                raise ValueError(
                    f"RADAR service name '{container_name}' already belongs to a "
                    f"running service with a different {label_key}."
                )

        logger.info(
            "RADAR service %s already exists with matching active workload",
            container_name,
        )
        return existing_service

    @staticmethod
    def _build_radar_config_fingerprint(environment: Dict[str, str]) -> str:
        """Build a stable fingerprint for fields that define RADAR behavior."""
        excluded_keys = {
            "SERVICE_ID",
            "RADAR_DATABASE_URL",
            "RADAR_TACTIC_SERVICE_HOST",
            "RADAR_TACTIC_SERVICE_PORT",
            "RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS",
        }
        comparable_environment = {
            key: value for key, value in environment.items() if key not in excluded_keys
        }
        serialized = json.dumps(
            comparable_environment,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def _remove_created_workload_after_failure(
        self,
        docker_workload: Any,
    ) -> None:
        """Best-effort cleanup for workloads created before DB persistence failed."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return
        try:
            await self._resolve_workload_operation(
                workload_id,
                on_service=lambda s: s.remove(),
                on_container=lambda c: c.remove(force=True),
            )
            logger.info(
                "Removed RADAR workload %s after failed service creation",
                workload_id,
            )
        except docker.errors.NotFound:
            logger.info(
                "RADAR workload %s already absent after failed service creation",
                workload_id,
            )
        except Exception:
            logger.exception(
                "Failed to remove RADAR workload %s after service creation failure",
                workload_id,
            )

    def _build_radar_environment(
        self,
        service_id: str,
        mqtt_topics: List[str],
        strategy: str,
        model_type: str,
        model_params: Dict[str, Any],
        preprocessing_steps: List[Dict[str, Any]],
        mqtt_config: Dict[str, Any],
        anomaly_thresholds: Dict[str, float],
        performance_config: Dict[str, Any],
        static_baseline_config: Dict[str, Any],
        adaptive_stream_config: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Build environment variables for RADAR service based on configuration.

        Maps the input parameters to RADAR-specific environment variables using
        Pydantic configuration defaults.
        """
        # Get RADAR defaults from configuration
        defaults = get_tactic_settings().config.radar_defaults
        runtime = get_radar_container_runtime_settings()
        strategy = (strategy or "adaptive_stream").strip().lower()
        if strategy not in {"static_baseline", "adaptive_stream"}:
            raise ValueError(
                "Invalid monitoring strategy. Expected static_baseline or "
                "adaptive_stream."
            )

        if strategy == "static_baseline":
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
            preprocessing_steps = []
            static_baseline_config = static_config.model_dump(
                exclude_none=True,
                exclude={"calibration_fraction", "fdr_config"},
            )
        else:
            nested_performance_config = adaptive_stream_config.get("performance_config")
            if nested_performance_config is None:
                nested_performance_config = {}
            if not isinstance(nested_performance_config, dict):
                raise ValueError(
                    "adaptive_stream_config.performance_config must be an object"
                )

            top_level_adaptive_performance = _extract_adaptive_performance_config(
                performance_config
            )
            adaptive_payload = {
                **adaptive_stream_config,
                "model_type": adaptive_stream_config.get(
                    "model_type", model_type or defaults.model_type
                ),
                "model_params": adaptive_stream_config.get(
                    "model_params", model_params or {}
                ),
                "preprocessing_steps": adaptive_stream_config.get(
                    "preprocessing_steps", preprocessing_steps or []
                ),
            }
            if nested_performance_config or top_level_adaptive_performance:
                adaptive_payload["performance_config"] = {
                    **nested_performance_config,
                    **top_level_adaptive_performance,
                }

            adaptive_config = AdaptiveStreamConfig(**adaptive_payload)
            model_type = adaptive_config.model_type
            model_params = adaptive_config.model_params
            preprocessing_steps = adaptive_config.preprocessing_steps
            adaptive_stream_config = adaptive_config.model_dump(exclude_none=True)
            if nested_performance_config or top_level_adaptive_performance:
                performance_config = {
                    **performance_config,
                    **adaptive_config.performance_config.model_dump(exclude_none=True),
                }

        env_vars = {
            "SERVICE_ID": service_id,
            "RADAR_MONITORING_STRATEGY": strategy,
            # TACTIC connectivity for model-registry calls from RADAR containers
            "RADAR_TACTIC_SERVICE_HOST": runtime.TACTIC_SERVICE_HOST,
            "RADAR_TACTIC_SERVICE_PORT": str(runtime.TACTIC_SERVICE_PORT),
            "RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS": str(
                runtime.TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS
            ),
            # MQTT Configuration
            "RADAR_MQTT_BROKER_HOST": mqtt_config.get(
                "host", defaults.mqtt_broker_host
            ),
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
            # Subscription Topics
            "RADAR_SUBSCRIPTION_TOPICS": ",".join(mqtt_topics),
            "RADAR_SUBSCRIPTION_QOS": str(mqtt_config.get("qos", defaults.mqtt_qos)),
            # Model Configuration
            "RADAR_MODEL_TYPE": model_type or defaults.model_type,
            "RADAR_STATIC_BASELINE_CONFIG": json.dumps(static_baseline_config),
            "RADAR_ADAPTIVE_STREAM_CONFIG": json.dumps(adaptive_stream_config),
            # Anomaly Thresholds
            "RADAR_ANOMALY_THRESHOLD_MEDIUM": str(
                anomaly_thresholds.get("medium", defaults.anomaly_threshold_medium)
            ),
            "RADAR_ANOMALY_THRESHOLD_HIGH": str(
                anomaly_thresholds.get("high", defaults.anomaly_threshold_high)
            ),
            "RADAR_ANOMALY_THRESHOLD_CRITICAL": str(
                anomaly_thresholds.get("critical", defaults.anomaly_threshold_critical)
            ),
            # Performance Settings
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
                performance_config.get(
                    "checkpoint_interval", defaults.checkpoint_interval
                )
            ),
            "RADAR_HEURISTIC_ENABLED": str(
                performance_config.get("heuristic_enabled", defaults.heuristic_enabled)
            ).lower(),
            "RADAR_HEURISTIC_WINDOW_SIZE": str(
                performance_config.get(
                    "heuristic_window_size", defaults.heuristic_window_size
                )
            ),
            "RADAR_HEURISTIC_MIN_SAMPLES": str(
                performance_config.get(
                    "heuristic_min_samples", defaults.heuristic_min_samples
                )
            ),
            "RADAR_HEURISTIC_TAIL_ALPHA": str(
                performance_config.get(
                    "heuristic_tail_alpha",
                    defaults.heuristic_tail_alpha,
                )
            ),
            "RADAR_SENSOR_KEY_STRATEGY": str(
                performance_config.get(
                    "sensor_key_strategy", defaults.sensor_key_strategy
                )
            ),
            "RADAR_ALIGNMENT_MODE": str(
                performance_config.get("alignment_mode", defaults.alignment_mode)
            ),
            "RADAR_SENSOR_FRESHNESS_SECONDS": str(
                performance_config.get(
                    "sensor_freshness_seconds", defaults.sensor_freshness_seconds
                )
            ),
            # Database Settings
            "RADAR_DB_WRITE_ENABLED": str(
                performance_config.get("db_write_enabled", defaults.db_write_enabled)
            ).lower(),
            "RADAR_DB_BATCH_SIZE": str(
                performance_config.get("db_batch_size", defaults.db_batch_size)
            ),
            "RADAR_DB_BATCH_TIMEOUT": str(
                performance_config.get("db_batch_timeout", defaults.db_batch_timeout)
            ),
            # Database URL - avoid Settings dependency in radar containers
            "RADAR_DATABASE_URL": self._build_database_url(),
            # Health and Monitoring
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

        # Validate and serialize model parameters using registry
        try:
            # Validate model_params against the registry schema
            validated_params = self.model_registry.validate_model_params(
                model_type, model_params, category="model"
            )

            # Serialize complete params as JSON for container to parse
            # Note: Individual RADAR_MODEL_* params removed - use only JSON
            env_vars["RADAR_MODEL_PARAMS"] = json.dumps(validated_params)
            if strategy == "static_baseline":
                static_baseline_config = {
                    **static_baseline_config,
                    "model_params": validated_params,
                }
                env_vars["RADAR_STATIC_BASELINE_CONFIG"] = json.dumps(
                    static_baseline_config
                )
            else:
                adaptive_stream_config = {
                    **adaptive_stream_config,
                    "model_params": validated_params,
                }
                env_vars["RADAR_ADAPTIVE_STREAM_CONFIG"] = json.dumps(
                    adaptive_stream_config
                )

            logger.info(f"Model params validated for {model_type}: {validated_params}")

        except ValueError as e:
            logger.error(f"Invalid model parameters for {model_type}: {e}")
            raise ValueError(f"Invalid model parameters: {e}")

        # Validate preprocessing steps
        try:
            validated_steps = self.model_registry.validate_preprocessing_steps(
                preprocessing_steps
            )
            env_vars["RADAR_PREPROCESSING_STEPS"] = json.dumps(validated_steps)
            if strategy == "adaptive_stream":
                adaptive_stream_config = {
                    **adaptive_stream_config,
                    "preprocessing_steps": validated_steps,
                }
                env_vars["RADAR_ADAPTIVE_STREAM_CONFIG"] = json.dumps(
                    adaptive_stream_config
                )
            logger.info(f"Preprocessing steps validated: {validated_steps}")
        except ValueError as e:
            logger.error(f"Invalid preprocessing steps: {e}")
            raise ValueError(f"Invalid preprocessing steps: {e}")

        return env_vars

    def _build_database_url(self) -> str:
        """
        Build async database URL from environment variables.

        This allows radar containers to connect to the database without
        depending on the full Settings class which requires many unrelated
        environment variables.
        """
        return get_radar_container_runtime_settings().radar_database_url

    async def _is_swarm_manager(self) -> bool:
        """Return True when Docker engine is an active Swarm manager.

        Result is cached for _SWARM_CACHE_TTL_SECONDS so that burst RADAR
        creation does not issue a docker.info() call per service. The TTL is
        short enough to react to cluster topology changes within a reasonable
        window without retaining stale state indefinitely.
        """
        global _swarm_manager_cache
        now = time.monotonic()
        if _swarm_manager_cache is not None:
            cached_result, expiry = _swarm_manager_cache
            if now < expiry:
                return cached_result
        try:
            info = await self.async_docker.run(self.async_docker.client.info)
            swarm = info.get("Swarm", {})
            local_node_state = str(swarm.get("LocalNodeState", "")).lower()
            result = local_node_state == "active" and bool(
                swarm.get("ControlAvailable")
            )
        except Exception as exc:
            logger.warning("Failed to detect Swarm mode; assuming non-Swarm: %s", exc)
            result = False
        _swarm_manager_cache = (result, now + _SWARM_CACHE_TTL_SECONDS)
        return result

    @staticmethod
    def _should_fallback_to_container(exc: Exception) -> bool:
        """Detect Swarm-only errors where local container fallback should be used."""
        # 503: node is not a Swarm manager or Swarm mode is not active.
        # 400/406: operation is only valid inside a Swarm context.
        if isinstance(exc, docker.errors.APIError) and exc.status_code in (
            400,
            406,
            503,
        ):
            return True
        # Secondary guard for Docker daemon versions that do not surface a
        # machine-readable status code for Swarm-specific errors.
        text = str(exc).lower()
        indicators = (
            "cannot be used with services",
            "only networks scoped to the swarm can be used",
            "this node is not a swarm manager",
            "swarm mode is not active",
        )
        return any(indicator in text for indicator in indicators)

    async def _create_radar_workload(
        self,
        service_id: str,
        environment: Dict[str, str],
    ) -> Any:
        """
        Create RADAR as a Swarm service when possible, otherwise as a Docker container.
        """
        if await self._is_swarm_manager():
            try:
                return await self._create_radar_swarm_service(
                    service_id=service_id,
                    environment=environment,
                )
            except Exception as exc:
                if not self._should_fallback_to_container(exc):
                    raise
                logger.warning(
                    "Swarm RADAR creation failed; falling back to container mode: %s",
                    exc,
                )

        return await self._create_radar_container(
            service_id=service_id,
            environment=environment,
        )

    async def _create_radar_swarm_service(
        self,
        service_id: str,
        environment: Dict[str, str],
    ) -> Any:
        """
        Helper method to create RADAR Docker service using Pydantic configuration.
        """
        # Get Docker configuration from Pydantic settings
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker

        labels = {
            "owner": "tactic_middleware",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "purpose": "RADAR anomaly detection service",
            "env": get_radar_container_runtime_settings().ENVIRONMENT,
            "service_type": "radar",
            "managed_by": "tactic",
            "monitoring_strategy": environment.get(
                "RADAR_MONITORING_STRATEGY", "adaptive_stream"
            ),
            "radar_model_type": environment.get("RADAR_MODEL_TYPE", ""),
            "radar_config_fingerprint": self._build_radar_config_fingerprint(
                environment
            ),
            "radar_image": tactic_config.radar_image,
        }

        service_kwargs = {
            "name": f"radar-{service_id}",
            "labels": labels,
            "image": tactic_config.radar_image,
            "env": environment,
            "command": ["/app/bin/python", "-m", "off_key_mqtt_radar"],
            "mode": ServiceMode("replicated", replicas=1),
            "restart_policy": RestartPolicy(
                condition=docker_config.default_restart_policy,
                max_attempts=docker_config.default_restart_max_attempts,
            ),
            "networks": [docker_config.default_network],
            "resources": Resources(
                cpu_limit=int(float(docker_config.default_cpu_limit) * 1_000_000_000),
                mem_limit=_parse_memory_string(docker_config.default_memory_limit),
            ),
        }

        if docker_config.default_constraints:
            service_kwargs["constraints"] = docker_config.default_constraints

        return await self.async_docker.run(
            self.async_docker.client.services.create,
            **service_kwargs,
        )

    async def _create_radar_container(
        self,
        service_id: str,
        environment: Dict[str, str],
    ) -> Any:
        """Helper method to create RADAR Docker container in non-Swarm mode."""
        tactic_config = get_tactic_settings().config
        docker_config = tactic_config.docker

        labels = {
            "owner": "tactic_middleware",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "purpose": "RADAR anomaly detection service",
            "env": get_radar_container_runtime_settings().ENVIRONMENT,
            "service_type": "radar",
            "managed_by": "tactic",
            "monitoring_strategy": environment.get(
                "RADAR_MONITORING_STRATEGY", "adaptive_stream"
            ),
            "radar_model_type": environment.get("RADAR_MODEL_TYPE", ""),
            "radar_config_fingerprint": self._build_radar_config_fingerprint(
                environment
            ),
            "radar_image": tactic_config.radar_image,
        }

        restart_policy: Dict[str, Any] = {
            "Name": docker_config.default_restart_policy,
        }
        if (
            docker_config.default_restart_policy == "on-failure"
            and docker_config.default_restart_max_attempts > 0
        ):
            restart_policy["MaximumRetryCount"] = (
                docker_config.default_restart_max_attempts
            )

        container_kwargs = {
            "name": f"radar-{service_id}",
            "labels": labels,
            "image": tactic_config.radar_image,
            "environment": environment,
            "command": ["/app/bin/python", "-m", "off_key_mqtt_radar"],
            "detach": True,
            "network": docker_config.default_network,
            "restart_policy": restart_policy,
            "mem_limit": _parse_memory_string(docker_config.default_memory_limit),
            "nano_cpus": int(float(docker_config.default_cpu_limit) * 1_000_000_000),
        }

        return await self.async_docker.run(
            self.async_docker.client.containers.run,
            **container_kwargs,
        )

    async def _validate_radar_workload_started(self, docker_workload: Any) -> None:
        """Fail service creation when RADAR exits or is rejected at startup."""
        workload_id = getattr(docker_workload, "id", None)
        if not workload_id:
            return

        grace_seconds = get_tactic_settings().config.radar_startup_grace_seconds
        if grace_seconds > 0:
            await asyncio.sleep(grace_seconds)

        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, workload_id
            )
            tasks = await self.async_docker.run(docker_service.tasks)
            self._raise_for_failed_swarm_task(workload_id, tasks)
            return
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not self._should_fallback_to_container(exc):
                raise
            logger.debug(
                "Skipping Swarm startup validation for workload %s: %s",
                workload_id,
                exc,
            )

        try:
            docker_container = await self.async_docker.run(
                self.async_docker.client.containers.get, workload_id
            )
            await self.async_docker.run(docker_container.reload)
        except docker.errors.NotFound as exc:
            raise RuntimeError(
                f"RADAR workload {workload_id} disappeared during startup"
            ) from exc

        status = str(getattr(docker_container, "status", "") or "unknown").lower()
        if status in {"exited", "dead", "restarting"}:
            logs = await self._get_container_log_tail(docker_container)
            message = (
                f"RADAR workload {workload_id} failed during startup (status={status})"
            )
            if logs:
                message = f"{message}. Recent logs:\n{logs}"
            raise RuntimeError(message)

    @staticmethod
    def _raise_for_failed_swarm_task(workload_id: str, tasks: List[Dict[str, Any]]):
        if not tasks:
            return

        latest_task = max(tasks, key=lambda task: str(task.get("CreatedAt", "")))
        status = latest_task.get("Status", {}) or {}
        state = str(status.get("State", "") or "unknown").lower()
        if state not in {
            "complete",
            "failed",
            "rejected",
            "shutdown",
            "orphaned",
            "remove",
        }:
            return

        detail = status.get("Err") or status.get("Message") or "no task error"
        raise RuntimeError(
            f"RADAR workload {workload_id} failed during startup "
            f"(task_state={state}): {detail}"
        )

    async def _get_container_log_tail(self, docker_container: Any) -> str:
        raw_logs = await self.async_docker.run(docker_container.logs, tail=120)
        if isinstance(raw_logs, bytes):
            logs = raw_logs.decode("utf-8", errors="replace")
        else:
            logs = str(raw_logs or "")
        return logs.strip()[-4000:]

    async def _resolve_workload_operation(
        self,
        container_id: str,
        on_service: Callable[[Any], Any],
        on_container: Callable[[Any], Any],
    ) -> Any:
        """Apply operation to Swarm service or fallback container by ID."""
        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, container_id
            )
            return await self.async_docker.run(on_service, docker_service)
        except docker.errors.NotFound:
            pass
        except Exception as exc:
            if not self._should_fallback_to_container(exc):
                raise
            logger.debug(
                "Skipping Swarm service lookup for workload %s: %s",
                container_id,
                exc,
            )

        docker_container = await self.async_docker.run(
            self.async_docker.client.containers.get, container_id
        )
        return await self.async_docker.run(on_container, docker_container)

    @staticmethod
    def _managed_radar_label_filters() -> Dict[str, List[str]]:
        return {"label": [MANAGED_BY_TACTIC_LABEL, RADAR_SERVICE_TYPE_LABEL]}

    async def _list_managed_radar_workload_ids(self) -> set[str]:
        filters = self._managed_radar_label_filters()

        try:
            docker_services = await self.async_docker.run(
                self.async_docker.client.services.list,
                filters=filters,
            )
        except Exception as exc:
            if not self._should_fallback_to_container(exc):
                raise
            logger.info(
                "Skipping Swarm service cleanup because this Docker engine does "
                "not support Swarm services: %s",
                exc,
            )
            docker_services = []

        docker_containers = await self.async_docker.run(
            self.async_docker.client.containers.list,
            all=True,
            filters=filters,
        )

        service_ids = {service.id for service in docker_services if service.id}
        container_ids = {
            container.id for container in docker_containers if container.id
        }
        return service_ids | container_ids

    async def teardown_managed_radar_workloads(self) -> Dict[str, int]:
        """
        Remove all TACTIC-managed RADAR Docker workloads and clear service records.

        Returns:
            Dict[str, int]: Cleanup summary counters.
        """
        managed_workload_ids = await self._list_managed_radar_workload_ids()
        target_ids = set(managed_workload_ids)

        removed_workloads = 0
        successfully_removed: set[str] = set()
        removal_failures: list[str] = []

        for workload_id in target_ids:
            try:
                await self._resolve_workload_operation(
                    workload_id,
                    on_service=lambda s: s.remove(),
                    on_container=lambda c: c.remove(force=True),
                )
                removed_workloads += 1
                successfully_removed.add(workload_id)
            except docker.errors.NotFound:
                # Workload already absent in Docker; DB row should still be cleaned up.
                successfully_removed.add(workload_id)
                continue
            except Exception as exc:
                removal_failures.append(f"{workload_id}: {exc}")

        db_rows_deleted = 0
        if successfully_removed:
            delete_result = await self.session.execute(
                delete(MonitoringService).where(
                    MonitoringService.container_id.in_(successfully_removed)
                )
            )
            db_rows_deleted = int(delete_result.rowcount or 0)
            await self.session.commit()

        if removal_failures:
            failures = "; ".join(removal_failures)
            raise RuntimeError(
                f"Failed to remove one or more managed RADAR workloads: {failures}"
            )

        return {
            "db_rows_deleted": db_rows_deleted,
            "docker_workloads_removed": removed_workloads,
            "workloads_targeted": len(target_ids),
        }

    async def stop_radar_service(
        self, container_name: Optional[str] = None, container_id: Optional[str] = None
    ) -> bool:
        """
        Stop and remove a running RADAR service.

        Args:
            container_name (str): Name of the container to stop
            container_id (str): ID of the container to stop

        Returns:
            bool: True if service was stopped, False otherwise
        """
        # Find the service in the database
        stmt = select(MonitoringService)

        if container_name:
            stmt = stmt.where(MonitoringService.container_name == container_name)
        elif container_id:
            stmt = stmt.where(MonitoringService.container_id == container_id)

        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            logger.warning(
                f"No RADAR service found with container name: {container_name}"
            )
            return False

        try:
            # Stop and remove the Docker workload (service or container)
            await self._resolve_workload_operation(
                service.container_id,
                on_service=lambda s: s.remove(),
                on_container=lambda c: c.remove(force=True),
            )

            service.status = False
            await self.session.commit()

            logger.info(
                f"RADAR container {container_name} "
                f"stopped and removed; DB record marked inactive"
            )
            return True

        except docker.errors.NotFound:
            # Container not found in Docker but exists in DB
            service.status = False
            await self.session.commit()

            logger.warning(
                f"RADAR container {container_name} not found in Docker "
                f"but marked as inactive in DB"
            )
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to stop RADAR container {container_name}: {e}")
            return False

    async def _get_docker_status(self, container_id: str) -> str:
        """Check actual Docker workload status (Swarm service or container)."""
        return await get_workload_docker_status(self.async_docker, container_id)

    async def _get_workload_labels(self, container_id: str) -> Dict[str, str]:
        """Read labels from the RADAR Swarm service or fallback container."""
        if not container_id:
            return {}
        try:
            try:
                docker_service = await self.async_docker.run(
                    self.async_docker.client.services.get, container_id
                )
                attrs = getattr(docker_service, "attrs", {}) or {}
                labels = attrs.get("Spec", {}).get("Labels", {}) or {}
                return {str(key): str(value) for key, value in labels.items()}
            except docker.errors.NotFound:
                docker_container = await self.async_docker.run(
                    self.async_docker.client.containers.get, container_id
                )
                await self.async_docker.run(docker_container.reload)
                attrs = getattr(docker_container, "attrs", {}) or {}
                labels = attrs.get("Config", {}).get("Labels", {}) or {}
                return {str(key): str(value) for key, value in labels.items()}
        except docker.errors.NotFound:
            return {}
        except Exception as exc:
            logger.debug("Error reading Docker labels for %s: %s", container_id, exc)
            return {}

    async def list_radar_services(
        self, active_only: bool = False, include_docker_status: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List all RADAR services.

        Args:
            active_only (bool): If True, only return active services
            include_docker_status (bool): If True, check actual Docker container
                status for each service (slower but more accurate)

        Returns:
            List[Dict]: List of RADAR services with their details
        """
        query = select(MonitoringService)
        if active_only:
            query = query.where(MonitoringService.status.is_(True))

        result = await self.session.execute(query)
        services = result.scalars().all()

        service_list = []
        for service in services:
            service_dict = {
                "id": service.id,
                "container_id": service.container_id,
                "container_name": service.container_name,
                "mqtt_topics": service.mqtt_topic,
                "status": service.status,
                "created_at": (
                    service.created_at.isoformat() if service.created_at else None
                ),
            }

            # Optionally check actual Docker state
            if include_docker_status:
                service_dict["docker_status"] = await self._get_docker_status(
                    service.container_id
                )
                labels = await self._get_workload_labels(service.container_id)
                if labels:
                    service_dict["monitoring_strategy"] = labels.get(
                        "monitoring_strategy"
                    )
                    service_dict["model_type"] = labels.get("radar_model_type")

            service_list.append(service_dict)

        return service_list

    async def get_radar_service(
        self, container_name: Optional[str] = None, container_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get details for a specific RADAR service.

        Args:
            container_name (str): Name of the container
            container_id (str): ID of the container

        Returns:
            Optional[Dict]: Service details or None if not found
        """
        stmt = select(MonitoringService)

        if container_name:
            stmt = stmt.where(MonitoringService.container_name == container_name)
        elif container_id:
            stmt = stmt.where(MonitoringService.container_id == container_id)

        result = await self.session.execute(stmt)
        service = result.scalars().first()

        if not service:
            return None

        # Check actual workload status in Docker
        docker_service_status = await self._get_docker_status(service.container_id)
        labels = await self._get_workload_labels(service.container_id)

        return {
            "id": service.id,
            "container_id": service.container_id,
            "container_name": service.container_name,
            "mqtt_topics": service.mqtt_topic,
            "db_status": service.status,
            "docker_status": docker_service_status,
            "monitoring_strategy": labels.get("monitoring_strategy"),
            "model_type": labels.get("radar_model_type"),
            "created_at": (
                service.created_at.isoformat() if service.created_at else None
            ),
        }
