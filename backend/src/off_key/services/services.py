import json
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any

import docker
from docker.types import RestartPolicy, ServiceMode
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ..core.logs import logger
from ..db.models import MonitoringService
from .async_docker import AsyncDocker

async_docker = AsyncDocker()


class MonitoringAsyncService:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session
        self.async_docker: AsyncDocker = async_docker
        logger.info("MonitoringAsyncService initialized.")

    async def create_monitoring_service(
        self,
        container_name: str,
        mqtt_topics: List[str],
        requirements: Optional[List[str]] = None,
        dockerfile_path: Optional[str] = None,
        app_path: Optional[str] = None,
        environment_variables: Optional[Dict[str, str]] = None,
    ) -> MonitoringService:
        """
        Create and start a Docker container for monitoring service asynchronously

        Args:
            container_name (str): Name for the Docker container
            mqtt_topics (list): List of MQTT topics to monitor
            requirements (list, optional): List of pip packages to install
            dockerfile_path (str, optional): Path to custom Dockerfile
            app_path (str, optional): Path to Python script
            environment_variables (dict, optional): Additional environment variables

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
            logger.info(f"Container {container_name} already exists and is running")
            return existing_service

        # Generate a unique service ID
        db_service_id = str(uuid.uuid4())

        # Check if template files exist and use defaults if not provided
        templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "resources"
        )
        default_dockerfile = os.path.join(templates_dir, "Dockerfile")
        default_app = os.path.join(templates_dir, "proxy.py")

        dockerfile_path = dockerfile_path or default_dockerfile
        app_path = app_path or default_app

        # Default requirements if none provided
        if requirements is None:
            requirements = ["paho-mqtt==1.6.1", "sqlalchemy==1.4.46"]

        # Set up environment variables
        env_vars = environment_variables or {}
        env_vars["MQTT_TOPICS"] = json.dumps(mqtt_topics)
        env_vars["SERVICE_ID"] = db_service_id

        # Create the container asynchronously
        try:
            service = await self._create_service_sync(
                container_name=container_name,
                service_id=db_service_id,
                dockerfile_path=dockerfile_path,
                app_path=app_path,
                requirements=requirements,
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

            logger.info(f"Service created with ID: {service.id}")
            logger.info(f"Service added to database with ID: {service_record.id}")

            return service_record

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to create monitoring service: {e}")
            raise

    async def _create_service_sync(
        self,
        container_name: str,
        service_id: str,
        dockerfile_path: str,
        app_path: str,
        requirements: List[str],
        environment: Dict[str, str],
    ) -> Any:
        """
        Helper method to handle Docker operations asynchronously
        """
        import tempfile
        import shutil

        # Create a unique build context
        build_context = tempfile.mkdtemp()

        try:
            # Copy Dockerfile and Python app to build context
            shutil.copy2(dockerfile_path, os.path.join(build_context, "Dockerfile"))
            shutil.copy2(app_path, os.path.join(build_context, "proxy.py"))

            # Create requirements.txt
            with open(os.path.join(build_context, "requirements.txt"), "w") as f:
                f.write("\n".join(requirements))

            # TODO: replace with monitoring image
            entrypoint = [
                "sh",
                "-c",
                (
                    "apk add --no-cache curl;"
                    "dd if=/dev/zero of=/dev/null bs=1M count=200 & "
                    "while true; "
                    "do curl -s https://httpbin.org/get > /dev/null; "
                    "sleep 5; done"
                ),
            ]
            labels = {
                "owner": "test_user",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "purpose": "This is a test",
                "env": "development",
            }
            container = await self.async_docker.run(
                self.async_docker.client.services.create,
                name=f"monitoring-service-{service_id}",
                labels=labels,
                image="alpine",
                command=entrypoint,
                mode=ServiceMode("replicated", replicas=1),
                restart_policy=RestartPolicy(condition="on-failure"),
                constraints=["node.role == worker"],
            )

            return container

        finally:
            # Clean up build context
            shutil.rmtree(build_context)

    async def stop_monitoring_service(
        self, container_name: Optional[str] = None, container_id: Optional[str] = None
    ) -> bool:
        """
        Stop and remove a running monitoring service

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
            logger.warning(f"No service found with container name: {container_name}")
            return False

        try:
            # Stop and remove all instances of the service
            service = await self.async_docker.run(
                self.async_docker.client.services.get, service.container_id
            )
            await self.async_docker.run(service.remove)

            # Delete the service from the database
            delete_stmt = delete(MonitoringService).where(
                MonitoringService.container_id == service.id
            )
            await self.session.execute(delete_stmt)
            await self.session.commit()

            logger.info(
                f"Container {container_name} stopped and removed; DB record deleted"
            )
            return True

        except docker.errors.NotFound:
            # Container not found in Docker but exists in DB
            # Delete the DB record to reflect this
            delete_stmt = delete(MonitoringService).where(
                MonitoringService.container_id == service.id
            )
            await self.session.execute(delete_stmt)
            await self.session.commit()

            logger.warning(
                f"Container {container_name} not found in Docker "
                f"but marked as inactive in DB"
            )
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to stop container {container_name}: {e}")
            return False

    async def list_monitoring_services(
        self, active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List all monitoring services

        Args:
            active_only (bool): If True, only return active services

        Returns:
            List[Dict]: List of services with their details
        """
        query = select(MonitoringService)
        if active_only:
            query = query.where(MonitoringService.status is True)

        result = await self.session.execute(query)
        services = result.scalars().all()

        service_list = []
        for service in services:
            service_list.append(
                {
                    "id": service.id,
                    "container_id": service.container_id,
                    "container_name": service.container_name,
                    "mqtt_topics": service.mqtt_topic,
                    "status": service.status,
                    "created_at": (
                        service.created_at.isoformat() if service.created_at else None
                    ),
                }
            )

        return service_list

    async def get_monitoring_service(
        self, container_name: Optional[str] = None, container_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get details for a specific monitoring service

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
            # For Docker services, we need to check tasks to get the actual status
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
