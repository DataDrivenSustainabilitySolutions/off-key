from fastapi import FastAPI, HTTPException
import docker
import uuid
from typing import Dict

app = FastAPI()
client = docker.from_env()

# Store active services
active_services: Dict[str, str] = {}


@app.post("/services/")
def create_service(mqtt_topic: str):
    """
    Starts a new Docker container running an ML worker for the given MQTT topic.
    """
    service_id = str(uuid.uuid4())
    container_name = f"ml_service_{service_id}"

    try:
        container = client.containers.run(
            "my_ml_worker_image",  # Replace with actual image
            name=container_name,
            detach=True,
            environment={
                "MQTT_TOPIC": mqtt_topic,
                "SERVICE_ID": service_id
            },
            network="my_mqtt_network",  # Ensure proper networking setup
            restart_policy={"Name": "always"}
        )
        active_services[service_id] = container.id
        return {"service_id": service_id, "container_id": container.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/services/{service_id}")
def stop_service(service_id: str):
    """
    Stops and removes a running ML worker container.
    """
    container_id = active_services.get(service_id)
    if not container_id:
        raise HTTPException(status_code=404, detail="Service not found")

    try:
        container = client.containers.get(container_id)
        container.stop()
        container.remove()
        del active_services[service_id]
        return {"message": "Service stopped and removed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
