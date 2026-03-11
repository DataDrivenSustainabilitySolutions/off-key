"""MQTT simulator service entrypoint."""

import asyncio
from datetime import datetime, timezone
import json
import math
import random
import signal
import ssl
import uuid

import paho.mqtt.client as mqtt

from off_key_core.config.env import load_env
from off_key_core.config.logs import logger
from off_key_core.config.validation import validate_settings

from .config import SimulatorConfig, get_simulator_settings


class SimulatorService:
    """Standalone publisher for synthetic telemetry data."""

    def __init__(self, config: SimulatorConfig):
        self.config = config
        self._shutdown_event = asyncio.Event()
        self._tick = 0

        self._client = mqtt.Client(
            client_id=f"{config.client_id_prefix}-{uuid.uuid4().hex[:8]}",
            transport="tcp",
        )
        if config.use_tls:
            context = ssl.create_default_context()
            self._client.tls_set_context(context)
        if config.use_auth:
            self._client.username_pw_set(config.username, config.api_key)

    def _build_value(self, feature: str, charger_index: int) -> float:
        feature_name = feature.strip().lower()
        base = 28.0 + (charger_index * 6.0)
        phase = (self._tick / 10.0) + (charger_index * 0.6)

        if feature_name == "sine":
            value = base + (8.0 * math.sin(phase)) + random.uniform(-0.8, 0.8)
        elif feature_name == "cosine":
            value = base + (8.0 * math.cos(phase)) + random.uniform(-0.8, 0.8)
        else:
            # Keep old stationary random style for "random" feature and fallback.
            value = base + (10.0 * random.random())

        return value

    def _inject_blip(self, value: float) -> tuple[float, bool]:
        if random.random() >= self.config.blip_probability:
            return value, False

        multiplier = random.uniform(
            self.config.blip_multiplier_min,
            self.config.blip_multiplier_max,
        )
        return value * multiplier, True

    def _build_payload(self, charger_id: str, feature: str, value: float) -> dict:
        return {
            self.config.payload_charger_key: charger_id,
            self.config.payload_type_key: feature,
            "value": round(value, 4),
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def _build_topic(self, charger_id: str, feature: str) -> str:
        return self.config.topic_template.format(
            charger_id=charger_id,
            feature=feature,
            telemetry_type=feature,
        )

    async def start(self) -> None:
        logger.info(
            "Starting MQTT simulator",
            extra={
                "broker": f"{self.config.broker_host}:{self.config.broker_port}",
                "chargers": self.config.charger_ids,
                "features": self.config.features,
                "interval_seconds": self.config.interval_seconds,
                "blip_probability": self.config.blip_probability,
                "blip_multiplier_range": (
                    self.config.blip_multiplier_min,
                    self.config.blip_multiplier_max,
                ),
            },
        )
        self._client.connect(self.config.broker_host, self.config.broker_port, 60)
        self._client.loop_start()

    async def stop(self) -> None:
        self._shutdown_event.set()
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTT simulator stopped")

    async def run(self) -> None:
        await self.start()
        try:
            while not self._shutdown_event.is_set():
                for charger_index, charger_id in enumerate(self.config.charger_ids):
                    for feature in self.config.features:
                        value = self._build_value(feature, charger_index)
                        value, blip_injected = self._inject_blip(value)
                        bounded_value = max(
                            self.config.value_min,
                            min(self.config.value_max, value),
                        )
                        topic = self._build_topic(charger_id, feature)
                        payload = self._build_payload(
                            charger_id, feature, bounded_value
                        )
                        self._client.publish(
                            topic,
                            json.dumps(payload),
                            qos=self.config.qos,
                            retain=False,
                        )
                        if blip_injected:
                            logger.info(
                                "Injected simulator blip | \
                                    charger=%s feature=%s value=%.4f",
                                charger_id,
                                feature,
                                bounded_value,
                            )
                self._tick += 1
                await asyncio.sleep(self.config.interval_seconds)
        finally:
            await self.stop()


async def main() -> None:
    load_env()
    validate_settings(
        [("mqtt_simulator", lambda: get_simulator_settings().config)],
        context="MQTT simulator configuration",
    )
    config = get_simulator_settings().config
    if not config.enabled:
        logger.info("MQTT simulator disabled by configuration")
        return

    service = SimulatorService(config)

    def _signal_handler(signum, frame):
        logger.info("Received signal %s, stopping MQTT simulator", signum)
        asyncio.create_task(service.stop())

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
