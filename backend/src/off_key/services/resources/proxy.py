import asyncio
import os
import paho.mqtt.client as mqtt
import httpx
from sqlalchemy import create_engine, sessionmaker
import logging

# Set up logging
logger = logging.getLogger("off_key.mqtt_proxy")
logger.setLevel(logging.INFO)

# Load ENV variables
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt://localhost")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db/ml")
WORKER_API_PORT = 8000  # FastAPI inside each worker listens here

# DB setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


# Placeholder models for MqttTopic and Service
# Replace with actual SQLAlchemy models from your app
class MqttTopic:
    def __init__(self, topic):
        self.topic = topic


class Service:
    def __init__(self, container_id):
        self.container_id = container_id


def get_active_topics():
    """Fetches active MQTT topics from the database."""
    session = SessionLocal()
    try:
        topics = session.query(MqttTopic.topic).distinct().all()
        return [t[0] for t in topics]
    finally:
        session.close()


def get_workers_for_topic(topic):
    """Returns a list of worker services subscribed to a topic."""
    session = SessionLocal()
    try:
        return (
            session.query(Service)
            .join(MqttTopic, Service.id == MqttTopic.service_id)
            .filter(MqttTopic.topic == topic)
            .all()
        )
    finally:
        session.close()


def on_message(client, userdata, msg):
    """Routes an MQTT message to the correct worker services."""
    topic = msg.topic
    payload = msg.payload.decode()

    logger.info(f"Received message on topic '{topic}': {payload}")

    # Get the workers subscribed to this topic
    workers = get_workers_for_topic(topic)

    if not workers:
        logger.warning(f"No workers found for topic '{topic}'")

    for worker in workers:
        worker_url = f"http://{worker.container_id}:{WORKER_API_PORT}/process"
        try:
            response = httpx.post(worker_url, json={"topic": topic, "data": payload})
            logger.info(f"Sent data to {worker_url}, Status: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send data to {worker_url}: {e}")


async def run_mqtt_proxy():
    """Subscribes to topics and routes messages."""
    client = mqtt.Client()
    client.on_message = on_message
    client.connect(MQTT_BROKER)

    # Fetch the active topics from the database
    topics = get_active_topics()
    if not topics:
        logger.warning("No active topics found in the database.")
    else:
        for topic in topics:
            client.subscribe(topic)
            logger.info(f"Subscribed to {topic}")

    client.loop_start()

    while True:
        await asyncio.sleep(5)  # Keep the event loop alive


if __name__ == "__main__":
    asyncio.run(run_mqtt_proxy())
