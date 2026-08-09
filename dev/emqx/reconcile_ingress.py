"""Idempotently reconcile the canonical Ambibox MQTT ingress in EMQX 6.2.2."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    model_validator,
)


class ReconcileSettings(BaseModel):
    """Secret-driven settings for the EMQX data-integration API."""

    model_config = ConfigDict(extra="forbid")

    api_url: str = Field(default="http://127.0.0.1:18083/api/v5", min_length=1)
    api_key: str = ""
    api_secret: SecretStr = SecretStr("")
    api_token: SecretStr = SecretStr("")
    connector_name: str = Field(default="ambibox", pattern=r"^[A-Za-z0-9_-]+$")
    source_name: str = Field(default="ambibox-wildcard", pattern=r"^[A-Za-z0-9_-]+$")
    rule_id: str = Field(default="ambibox-device-ingress", pattern=r"^[A-Za-z0-9_-]+$")
    upstream_server: str = Field(min_length=1)
    upstream_username: str = ""
    upstream_password: SecretStr = SecretStr("")
    upstream_tls: bool = False
    upstream_qos: int = Field(default=1, ge=0, le=2)
    check_only: bool = False
    verification_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    verification_poll_seconds: float = Field(default=1.0, gt=0.0, le=30.0)

    @model_validator(mode="after")
    def validate_api_authentication(self) -> ReconcileSettings:
        if self.api_token.get_secret_value():
            return self
        if not self.api_key or not self.api_secret.get_secret_value():
            raise ValueError(
                "Set EMQX_API_TOKEN or both EMQX_API_KEY and EMQX_API_SECRET"
            )
        return self

    @classmethod
    def from_environment(cls) -> ReconcileSettings:
        values: dict[str, Any] = {
            "api_key": os.getenv("EMQX_API_KEY", ""),
            "api_secret": os.getenv("EMQX_API_SECRET", ""),
            "api_token": os.getenv("EMQX_API_TOKEN", ""),
            "upstream_server": os.getenv("AMBIBOX_MQTT_SERVER", ""),
        }
        optional = {
            "api_url": "EMQX_API_URL",
            "connector_name": "EMQX_AMBIBOX_CONNECTOR_NAME",
            "source_name": "EMQX_AMBIBOX_SOURCE_NAME",
            "rule_id": "EMQX_AMBIBOX_RULE_ID",
            "upstream_username": "AMBIBOX_MQTT_USERNAME",
            "upstream_password": "AMBIBOX_MQTT_PASSWORD",
            "upstream_tls": "AMBIBOX_MQTT_TLS",
            "upstream_qos": "AMBIBOX_MQTT_QOS",
            "check_only": "EMQX_RECONCILE_CHECK_ONLY",
            "verification_timeout_seconds": "EMQX_RECONCILE_TIMEOUT_SECONDS",
            "verification_poll_seconds": "EMQX_RECONCILE_POLL_SECONDS",
        }
        for field_name, env_name in optional.items():
            value = os.getenv(env_name)
            if value is not None:
                values[field_name] = value
        return cls.model_validate(values)


@dataclass(frozen=True)
class Resource:
    collection_path: str
    item_path: str
    payload: dict[str, Any]
    verification_payload: dict[str, Any]
    healthy_status: str | None = None


def _configuration_mismatch(
    expected: Any,
    actual: Any,
    path: str = "resource",
) -> str | None:
    """Return the first non-secret mismatch in an EMQX API response."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return f"{path} must be an object"
        for key, expected_value in expected.items():
            if key not in actual:
                return f"{path}.{key} is missing"
            mismatch = _configuration_mismatch(
                expected_value, actual[key], f"{path}.{key}"
            )
            if mismatch:
                return mismatch
        return None

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return f"{path} must be a list"
        if len(actual) != len(expected):
            return f"{path} has {len(actual)} entries; expected {len(expected)}"
        for index, (expected_value, actual_value) in enumerate(
            zip(expected, actual, strict=True)
        ):
            mismatch = _configuration_mismatch(
                expected_value, actual_value, f"{path}[{index}]"
            )
            if mismatch:
                return mismatch
        return None

    if actual != expected:
        return f"{path} is {actual!r}; expected {expected!r}"
    return None


class EmqxClient:
    def __init__(self, settings: ReconcileSettings):
        self.settings = settings
        token = settings.api_token.get_secret_value()
        if token:
            self.authorization = f"Bearer {token}"
        else:
            credentials = (
                f"{settings.api_key}:{settings.api_secret.get_secret_value()}".encode()
            )
            self.authorization = "Basic " + base64.b64encode(credentials).decode()

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            f"{self.settings.api_url.rstrip('/')}/{path.lstrip('/')}",
            data=body,
            method=method,
            headers={
                "Authorization": self.authorization,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                response_body = response.read()
                return response.status, (
                    json.loads(response_body) if response_body else None
                )
        except HTTPError as error:
            response_body = error.read()
            detail = response_body.decode(errors="replace")
            if error.code == 404:
                return error.code, None
            raise RuntimeError(
                f"EMQX API {method} {path} failed with HTTP {error.code}: {detail}"
            ) from error

    def reconcile(self, resource: Resource) -> str:
        status, current = self.request("GET", resource.item_path)
        if self.settings.check_only:
            if status == 404:
                raise RuntimeError(f"Missing EMQX resource: {resource.item_path}")
            mismatch = self._verification_mismatch(resource, current)
            if mismatch:
                raise RuntimeError(
                    f"EMQX resource verification failed for "
                    f"{resource.item_path}: {mismatch}"
                )
            return "verified"

        if status == 404:
            create_status, _ = self.request(
                "POST", resource.collection_path, resource.payload
            )
            if create_status not in {200, 201, 204}:
                raise RuntimeError(f"Unable to create {resource.item_path}")
            self._wait_until_verified(resource)
            return "created"

        update_payload = dict(resource.payload)
        update_payload.pop("type", None)
        update_payload.pop("name", None)
        update_payload.pop("id", None)
        update_status, _ = self.request("PUT", resource.item_path, update_payload)
        if update_status not in {200, 204}:
            raise RuntimeError(f"Unable to update {resource.item_path}")
        self._wait_until_verified(resource)
        return "updated" if current is not None else "reconciled"

    @staticmethod
    def _verification_mismatch(resource: Resource, current: Any) -> str | None:
        mismatch = _configuration_mismatch(resource.verification_payload, current)
        if mismatch:
            return mismatch
        if resource.healthy_status is not None:
            actual_status = current.get("status") if isinstance(current, dict) else None
            if actual_status != resource.healthy_status:
                return (
                    f"resource.status is {actual_status!r}; "
                    f"expected {resource.healthy_status!r}"
                )
        return None

    def _wait_until_verified(self, resource: Resource) -> None:
        deadline = time.monotonic() + self.settings.verification_timeout_seconds
        last_mismatch = "resource was not returned"
        while True:
            status, current = self.request("GET", resource.item_path)
            if status != 404:
                mismatch = self._verification_mismatch(resource, current)
                if mismatch is None:
                    return
                last_mismatch = mismatch

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Timed out verifying EMQX resource {resource.item_path}: "
                    f"{last_mismatch}"
                )
            time.sleep(self.settings.verification_poll_seconds)


def desired_resources(settings: ReconcileSettings) -> list[Resource]:
    connector_id = quote(f"mqtt:{settings.connector_name}", safe="")
    source_id = quote(f"mqtt:{settings.source_name}", safe="")
    rule_id = quote(settings.rule_id, safe="")
    connector_payload: dict[str, Any] = {
        "type": "mqtt",
        "name": settings.connector_name,
        "enable": True,
        "server": settings.upstream_server,
        "proto_ver": "v4",
        "clean_start": True,
        "connect_timeout": "10s",
        "keepalive": "60s",
        "retry_interval": "15s",
        "pool_size": 8,
        "ssl": {"enable": settings.upstream_tls},
    }
    if settings.upstream_username:
        connector_payload["username"] = settings.upstream_username
    if settings.upstream_password.get_secret_value():
        connector_payload["password"] = settings.upstream_password.get_secret_value()
    connector_verification = {
        key: value for key, value in connector_payload.items() if key != "password"
    }

    source_payload = {
        "type": "mqtt",
        "name": settings.source_name,
        "enable": True,
        "connector": settings.connector_name,
        "parameters": {
            "topic": "device/#",
            "qos": settings.upstream_qos,
        },
    }
    rule_payload = {
        "id": settings.rule_id,
        "name": "Ambibox device ingress",
        "enable": True,
        "sql": (f'SELECT * FROM "$bridges/mqtt:{settings.source_name}"'),
        "actions": [
            {
                "function": "republish",
                "args": {
                    "topic": "${topic}",
                    "payload": "${payload}",
                    "qos": "${qos}",
                    "retain": False,
                    "direct_dispatch": True,
                },
            }
        ],
    }
    return [
        Resource(
            collection_path="connectors",
            item_path=f"connectors/{connector_id}",
            payload=connector_payload,
            verification_payload=connector_verification,
            healthy_status="connected",
        ),
        Resource(
            collection_path="sources",
            item_path=f"sources/{source_id}",
            payload=source_payload,
            verification_payload=source_payload,
            healthy_status="connected",
        ),
        Resource(
            collection_path="rules",
            item_path=f"rules/{rule_id}",
            payload=rule_payload,
            verification_payload=rule_payload,
        ),
    ]


def main() -> int:
    try:
        settings = ReconcileSettings.from_environment()
        client = EmqxClient(settings)
        for resource in desired_resources(settings):
            result = client.reconcile(resource)
            print(f"{result}: {resource.item_path}")
    except (ValidationError, RuntimeError) as error:
        print(f"EMQX ingress reconciliation failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
