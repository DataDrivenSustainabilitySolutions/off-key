import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any

import docker
from docker.types import RestartPolicy, ServiceMode, Resources
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from off_key_core.config.logs import logger
from off_key_core.db.models import MonitoringService
from off_key_core.models import validate_model_params, validate_preprocessing_steps
from ...facades.docker import AsyncDocker
from ...config import tactic_settings

async_docker = AsyncDocker()


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

    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.async_docker: AsyncDocker = async_docker
        logger.info("RadarOrchestrationService initialized.")

    async def create_radar_service(
        self,
        container_name: str,
        mqtt_topics: List[str],
        model_type: str = "isolation_forest",
        model_params: Optional[Dict[str, Any]] = None,
        preprocessing_steps: Optional[List[Dict[str, Any]]] = None,
        mqtt_config: Optional[Dict[str, Any]] = None,
        anomaly_thresholds: Optional[Dict[str, float]] = None,
        performance_config: Optional[Dict[str, Any]] = None,
    ) -> MonitoringService:
        """
        Create and start a RADAR Docker service for anomaly detection.

        Args:
            container_name (str): Name for the Docker container
            mqtt_topics (List[str]): List of MQTT topics to monitor
            model_type (str): Type of ML model (isolation_forest, adaptive_svm, knn)
            model_params (Dict, optional): Model-specific parameters
            preprocessing_steps (List[Dict], optional): Preprocessing pipeline steps
            mqtt_config (Dict, optional): MQTT connection configuration
            anomaly_thresholds (Dict, optional): Anomaly detection thresholds
            performance_config (Dict, optional): Performance and resource settings

        Returns:
            MonitoringService: The created monitoring service database entry
        """
        # Check if service with this name already exists
        query = select(MonitoringService).where(
            MonitoringService.container_name == container_name
        )
        result = await self.session.execute(query)
        existing_service = result.scalars().first()

        if existing_service and existing_service.status:
            logger.info(
                f"RADAR container {container_name} already exists and is running"
            )
            return existing_service

        # Generate a unique service ID
        db_service_id = str(uuid.uuid4())

        # Build environment variables for RADAR service
        env_vars = self._build_radar_environment(
            service_id=db_service_id,
            mqtt_topics=mqtt_topics,
            model_type=model_type,
            model_params=model_params or {},
            preprocessing_steps=preprocessing_steps or [],
            mqtt_config=mqtt_config or {},
            anomaly_thresholds=anomaly_thresholds or {},
            performance_config=performance_config or {},
        )

        # Create the RADAR service
        try:
            service = await self._create_radar_service_sync(
                container_name=container_name,
                service_id=db_service_id,
                environment=env_vars,
            )

            # Create monitoring service record
            service_record = MonitoringService(
                id=db_service_id,
                container_id=service.id,
                container_name=container_name,
                mqtt_topic=mqtt_topics,
                created_at=datetime.now(),
                status=True,
            )

            # Add to database
            self.session.add(service_record)
            await self.session.commit()

            logger.info(f"RADAR service created with ID: {service.id}")
            logger.info(f"RADAR service added to database with ID: {service_record.id}")

            return service_record

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to create RADAR service: {e}")
            raise

    def _build_radar_environment(
        self,
        service_id: str,
        mqtt_topics: List[str],
        model_type: str,
        model_params: Dict[str, Any],
        preprocessing_steps: List[Dict[str, Any]],
        mqtt_config: Dict[str, Any],
        anomaly_thresholds: Dict[str, float],
        performance_config: Dict[str, Any],
    ) -> Dict[str, str]:
        """
        Build environment variables for RADAR service based on configuration.

        Maps the input parameters to RADAR-specific environment variables using
        Pydantic configuration defaults.
        """
        # Get RADAR defaults from configuration
        defaults = tactic_settings.config.radar_defaults

        env_vars = {
            "SERVICE_ID": service_id,
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
            validated_params = validate_model_params(model_type, model_params)

            # Serialize complete params as JSON for container to parse
            env_vars["RADAR_MODEL_PARAMS"] = json.dumps(validated_params)

            # Also set individual params for backward compatibility and debugging
            for key, value in validated_params.items():
                env_key = f"RADAR_MODEL_{key.upper()}"
                env_vars[env_key] = str(value)

            logger.info(f"Model params validated for {model_type}: {validated_params}")

        except ValueError as e:
            logger.error(f"Invalid model parameters for {model_type}: {e}")
            raise ValueError(f"Invalid model parameters: {e}")

        # Validate preprocessing steps
        try:
            validated_steps = validate_preprocessing_steps(preprocessing_steps)
            env_vars["RADAR_PREPROCESSING_STEPS"] = json.dumps(validated_steps)
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
        postgres_user = os.getenv("POSTGRES_USER", "postgres")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        postgres_host = os.getenv("POSTGRES_HOST", "timescaledb")
        postgres_port = os.getenv("POSTGRES_PORT", "5432")
        postgres_db = os.getenv("POSTGRES_DB", "postgres")

        return (
            f"postgresql+asyncpg://{postgres_user}:{postgres_password}"
            f"@{postgres_host}:{postgres_port}/{postgres_db}"
        )

    async def _create_radar_service_sync(
        self,
        container_name: str,
        service_id: str,
        environment: Dict[str, str],
    ) -> Any:
        """
        Helper method to create RADAR Docker service using Pydantic configuration.
        """
        # Get Docker configuration from Pydantic settings
        docker_config = tactic_settings.config.docker

        labels = {
            "owner": "tactic_middleware",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "purpose": "RADAR anomaly detection service",
            "env": os.getenv("ENVIRONMENT", "development"),
            "service_type": "radar",
            "managed_by": "tactic",
        }

        service_kwargs = {
            "name": f"radar-{service_id}",
            "labels": labels,
            "image": "off-key-mqtt-radar:latest",
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

        container = await self.async_docker.run(
            self.async_docker.client.services.create,
            **service_kwargs,
        )

        return container

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
            # Stop and remove the Docker service
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, service.container_id
            )
            await self.async_docker.run(docker_service.remove)

            # Delete the service from the database
            delete_stmt = delete(MonitoringService).where(
                MonitoringService.container_id == service.container_id
            )
            await self.session.execute(delete_stmt)
            await self.session.commit()

            logger.info(
                f"RADAR container {container_name} "
                f"stopped and removed; DB record deleted"
            )
            return True

        except docker.errors.NotFound:
            # Container not found in Docker but exists in DB
            delete_stmt = delete(MonitoringService).where(
                MonitoringService.container_id == service.container_id
            )
            await self.session.execute(delete_stmt)
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
        """
        Check actual Docker container status.

        Args:
            container_id: Docker service/container ID

        Returns:
            str: Status string - "running", "complete", "failed",
                 "no_tasks", "not_found", or "error"
        """
        if not container_id:
            return "no_container_id"

        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, container_id
            )
            tasks = await self.async_docker.run(docker_service.tasks)
            if tasks:
                # Get the most recent task
                latest = max(tasks, key=lambda t: t.get("CreatedAt", ""))
                return latest.get("Status", {}).get("State", "unknown")
            return "no_tasks"
        except docker.errors.NotFound:
            return "not_found"
        except Exception as e:
            logger.error(f"Failed to get Docker status for {container_id}: {e}")
            return "error"

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

        # Check actual service status in Docker
        docker_service_status = "unknown"
        try:
            docker_service = await self.async_docker.run(
                self.async_docker.client.services.get, service.container_id
            )
            # For Docker services, check tasks to get the actual status
            tasks = await self.async_docker.run(docker_service.tasks)
            if tasks:
                # Get the status of the most recent task
                latest_task = max(tasks, key=lambda t: t.get("CreatedAt", ""))
                docker_service_status = latest_task.get("Status", {}).get(
                    "State", "unknown"
                )
            else:
                docker_service_status = "no_tasks"
        except docker.errors.NotFound:
            docker_service_status = "not_found"
        except Exception as e:
            logger.error(f"Error checking Docker service status: {e}")
            docker_service_status = "error"

        return {
            "id": service.id,
            "container_id": service.container_id,
            "container_name": service.container_name,
            "mqtt_topics": service.mqtt_topic,
            "db_status": service.status,
            "docker_status": docker_service_status,
            "created_at": (
                service.created_at.isoformat() if service.created_at else None
            ),
        }
