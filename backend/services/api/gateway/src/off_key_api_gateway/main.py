"""ASGI entry point: ``uvicorn off_key_api_gateway.main:app``."""

from .app import create_app, health_check

app = create_app()

__all__ = ["app", "health_check"]
