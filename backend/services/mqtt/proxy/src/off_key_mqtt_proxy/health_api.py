"""
Lightweight health/readiness API for MQTT proxy service.
"""

import json
from typing import Any

import uvicorn

from off_key_core.config.logs import logger
from .config.config import get_mqtt_settings
from .proxy import MQTTProxyService


class ProxyHealthApp:
    """Minimal ASGI app that exposes liveness/readiness for orchestration."""

    def __init__(self, service: MQTTProxyService):
        self.service = service

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope["path"]

        if method != "GET":
            await self._send_json(
                send,
                status=405,
                body={"status": "method_not_allowed", "allowed_methods": ["GET"]},
            )
            return

        if path in {"/health", "/health/live"}:
            await self._send_json(
                send,
                status=200,
                body={
                    "status": "healthy",
                    "service": "mqtt-proxy",
                    "running": self.service.is_running,
                },
            )
            return

        if path in {"/ready", "/ready/bridge"}:
            readiness = self.service.get_readiness_status()
            await self._send_json(
                send,
                status=200 if readiness["ready"] else 503,
                body=readiness,
            )
            return

        if path == "/health/full":
            await self._send_json(
                send,
                status=200,
                body=self.service.get_health_status(),
            )
            return

        await self._send_json(
            send,
            status=404,
            body={"status": "not_found", "path": path},
        )

    async def _send_json(self, send, *, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, default=str).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]

        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": payload})


async def run_health_api(service: MQTTProxyService) -> None:
    """Run health API server for orchestrator probes."""
    settings = get_mqtt_settings()
    host = settings.MQTT_HEALTH_API_HOST
    port = settings.MQTT_HEALTH_API_PORT

    config = uvicorn.Config(
        ProxyHealthApp(service),
        host=host,
        port=port,
        log_config=None,
    )
    server = uvicorn.Server(config)

    logger.info(
        "Starting MQTT proxy health API on %s:%s",
        host,
        port,
    )
    await server.serve()
