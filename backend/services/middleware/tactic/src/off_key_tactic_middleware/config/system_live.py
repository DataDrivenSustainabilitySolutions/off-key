"""Private operator controls for temporary generic MQTT observation."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Literal, Self

from off_key_core.config.validation import SECRETS_DIR
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class LiveCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(default="", max_length=512)
    password: SecretStr = SecretStr("")


class LiveSocksProxy(LiveCredential):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=1055, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def exact_proxy_host(cls, value: str) -> str:
        from off_key_core.schemas.system import SystemConnection

        return SystemConnection(id="validation", label="Proxy", host=value).host


def _exact_host(value: str) -> str:
    from off_key_core.schemas.system import SystemConnection

    return SystemConnection(id="validation", label="Broker", host=value).host


class BrokerRoute(BaseModel):
    """Operator-provided access to a broker network: which hosts it covers and
    how to reach them. Covered hosts need no entry in SYSTEM_LIVE_ALLOWED_HOSTS."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    hosts: list[str] = Field(default_factory=list, max_length=128)
    # Each suffix starts with a dot and matches whole DNS labels only.
    host_suffixes: list[str] = Field(default_factory=list, max_length=16)
    socks_proxy: LiveSocksProxy | None = None
    credential: LiveCredential | None = None
    require_tls: bool = False

    @field_validator("hosts")
    @classmethod
    def exact_hosts(cls, hosts: list[str]) -> list[str]:
        return [_exact_host(host) for host in hosts]

    @field_validator("host_suffixes")
    @classmethod
    def label_suffixes(cls, suffixes: list[str]) -> list[str]:
        result = []
        for suffix in suffixes:
            if not suffix.startswith("."):
                raise ValueError("Host suffixes start with a dot, such as .example.net")
            result.append("." + _exact_host(suffix[1:]))
        return result

    @model_validator(mode="after")
    def covers_hosts(self) -> Self:
        if not self.hosts and not self.host_suffixes:
            raise ValueError("A broker route covers at least one host or suffix")
        return self

    def covers(self, host: str) -> bool:
        return host in self.hosts or any(
            host.endswith(suffix) for suffix in self.host_suffixes
        )


@dataclass(frozen=True)
class CollectionOutputEndpoint:
    """Where TACTIC publishes accepted readings for mqtt-proxy to store."""

    host: str
    port: int
    use_tls: bool
    ca_file: str | None
    username: str | None = None
    password: SecretStr | None = field(default=None, repr=False)


class SystemLiveSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir=SECRETS_DIR,
    )

    SYSTEM_LIVE_ENABLED: bool = False
    SYSTEM_COLLECTION_ENABLED: bool = True
    SYSTEM_COLLECTION_MQTT_USERNAME: str = ""
    SYSTEM_COLLECTION_MQTT_API_KEY: SecretStr = SecretStr("")
    SYSTEM_COLLECTION_MQTT_CA_FILE: str | None = None
    # A recorded broker unreachable this long is reported unavailable and its
    # client stopped; quiet retries then back off from the first to the max delay.
    SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=600)
    SYSTEM_COLLECTION_RETRY_SECONDS: int = Field(default=300, ge=10, le=3600)
    SYSTEM_COLLECTION_RETRY_MAX_SECONDS: int = Field(default=3600, ge=10, le=86400)
    SYSTEM_LIVE_DATA_SOURCE: Literal["broker", "simulated"] = "broker"
    SYSTEM_LIVE_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    SYSTEM_LIVE_CREDENTIALS: Annotated[dict[str, LiveCredential], NoDecode] = Field(
        default_factory=dict
    )
    SYSTEM_LIVE_SOCKS_PROXIES: Annotated[dict[str, LiveSocksProxy], NoDecode] = Field(
        default_factory=dict, max_length=128
    )
    # Operator broker routes, delivered as one JSON secret; the first match wins.
    SYSTEM_BROKER_ROUTES: Annotated[list[BrokerRoute], NoDecode] = Field(
        default_factory=list, max_length=16
    )
    SYSTEM_LIVE_MAX_CONNECTIONS: int = Field(default=32, ge=1, le=128)
    SYSTEM_LIVE_MAX_STREAMS: int = Field(default=4096, ge=1, le=4096)
    SYSTEM_LIVE_MAX_SAMPLES: int = Field(default=8192, ge=64, le=65536)
    SYSTEM_LIVE_LEASE_SECONDS: int = Field(default=45, ge=15, le=120)
    SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS: int = Field(default=15, ge=5, le=120)
    # On-demand reachability checks: one CONNECT each, never a subscription.
    SYSTEM_CONNECTION_CHECK_TIMEOUT_SECONDS: float = Field(default=8, ge=1, le=30)
    SYSTEM_CONNECTION_CHECK_CONCURRENCY: int = Field(default=4, ge=1, le=16)

    def collection_output_endpoint(self, radar_defaults) -> CollectionOutputEndpoint:
        """The broker mqtt-proxy subscribes on, reached with the managed RADAR
        broker defaults; the collection account falls back to RADAR's user."""
        auth = radar_defaults.mqtt_use_auth
        return CollectionOutputEndpoint(
            host=radar_defaults.mqtt_broker_host,
            port=radar_defaults.mqtt_broker_port,
            use_tls=radar_defaults.mqtt_use_tls,
            ca_file=self.SYSTEM_COLLECTION_MQTT_CA_FILE,
            username=(
                self.SYSTEM_COLLECTION_MQTT_USERNAME or radar_defaults.mqtt_username
                if auth
                else None
            ),
            password=self.SYSTEM_COLLECTION_MQTT_API_KEY if auth else None,
        )

    @field_validator(
        "SYSTEM_LIVE_CREDENTIALS", "SYSTEM_LIVE_SOCKS_PROXIES", mode="before"
    )
    @classmethod
    def private_credentials(cls, value):
        return json.loads(value or "{}") if isinstance(value, str) else value

    @field_validator("SYSTEM_BROKER_ROUTES", mode="before")
    @classmethod
    def private_routes(cls, value):
        return json.loads(value or "[]") if isinstance(value, str) else value

    @field_validator("SYSTEM_BROKER_ROUTES")
    @classmethod
    def unique_route_names(cls, routes: list[BrokerRoute]) -> list[BrokerRoute]:
        names = [route.name for route in routes]
        if len(names) != len(set(names)):
            raise ValueError("Broker route names must be unique")
        return routes

    @field_validator("SYSTEM_LIVE_SOCKS_PROXIES")
    @classmethod
    def exact_proxy_routes(cls, proxies: dict[str, LiveSocksProxy]):
        return {_exact_host(host): proxy for host, proxy in proxies.items()}

    @field_validator("SYSTEM_LIVE_ALLOWED_HOSTS")
    @classmethod
    def exact_hosts(cls, hosts: list[str]) -> list[str]:
        return [_exact_host(host) for host in hosts]

    def allows_host(self, host: str) -> bool:
        return host in self.SYSTEM_LIVE_ALLOWED_HOSTS

    def route_for(self, host: str) -> BrokerRoute | None:
        return next(
            (route for route in self.SYSTEM_BROKER_ROUTES if route.covers(host)), None
        )

    @property
    def limits(self) -> dict[str, int]:
        return {
            "max_connections": self.SYSTEM_LIVE_MAX_CONNECTIONS,
            "max_streams": self.SYSTEM_LIVE_MAX_STREAMS,
            "max_samples": self.SYSTEM_LIVE_MAX_SAMPLES,
            "max_payload_bytes": 65536,
            "max_text_length": 512,
            "sample_interval_seconds": 1,
            "history_seconds": 7200,
            "lease_seconds": self.SYSTEM_LIVE_LEASE_SECONDS,
            "connect_timeout_seconds": self.SYSTEM_LIVE_CONNECT_TIMEOUT_SECONDS,
        }


@lru_cache(maxsize=1)
def get_system_live_settings() -> SystemLiveSettings:
    return SystemLiveSettings()
