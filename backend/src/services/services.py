import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime

import docker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.src.core.logs import logger
from backend.src.db.base import Base
from backend.src.db.models import MonitoringService


def create_monitoring_container(
    container_name,
    mqtt_topics,
    db_url,
    requirements=None,
    dockerfile_path=None,
    app_path=None,
):
    """
    Create and start a Docker container for monitoring service using a Dockerfile

    Args:
        container_name (str): Name for the Docker container
        mqtt_topics (list): List of MQTT topics to monitor
        db_url (str): Database URL for SQLAlchemy
        requirements (list): List of pip packages to install
        dockerfile_path (str): Path to custom Dockerfile
        app_path (str): Path to custom src.py

    Returns:
        MonitoringService: The created monitoring service database entry
    """
    # Check if template files exist
    templates_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "templates"
    )
    default_dockerfile = os.path.join(templates_dir, "Dockerfile")
    default_app = os.path.join(templates_dir, "src.py")

    # Use provided paths or defaults
    dockerfile_path = dockerfile_path or default_dockerfile
    app_path = app_path or default_app

    # Default requirements if none provided
    if requirements is None:
        requirements = ["paho-mqtt==1.6.1", "sqlalchemy==1.4.46"]

    # Create a unique build context
    service_id = str(uuid.uuid4())
    build_context = tempfile.mkdtemp()

    try:
        # Copy Dockerfile and src.py to build context
        shutil.copy2(dockerfile_path, os.path.join(build_context, "Dockerfile"))
        shutil.copy2(app_path, os.path.join(build_context, "src.py"))

        # Create requirements.txt
        with open(os.path.join(build_context, "requirements.txt"), "w") as f:
            f.write("\n".join(requirements))

        # Connect to Docker
        client = docker.from_env()

        # Build the Docker image with a unique tag
        image_tag = f"monitoring-service:{service_id}"
        image, build_logs = client.images.build(
            path=build_context, tag=image_tag, rm=True, forcerm=True
        )

        # Run the container
        container = client.containers.run(
            image=image_tag,
            name=container_name,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            environment={
                "MQTT_TOPICS": json.dumps(mqtt_topics),
                "SERVICE_ID": service_id,
            },
        )

        # Create database engine and session
        engine = create_engine(db_url)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        # Create monitoring service record
        service = MonitoringService(
            id=service_id,
            container_id=container.id,
            mqtt_topic=mqtt_topics,
            created_at=datetime.now(),
            status=True,
        )

        # Add and commit to database
        session.add(service)
        session.commit()

        logger.info(f"Container created with ID: {container.id}")
        logger.info(f"Service added to database with ID: {service.id}")
        logger.info(f"Installed requirements: {', '.join(requirements)}")

        return service

    finally:
        # Clean up build context
        shutil.rmtree(build_context)
