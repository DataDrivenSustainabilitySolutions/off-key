"""Private operator controls for temporary generic MQTT observation."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Literal

from off_key_core.config.validation import SECRETS_DIR
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
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
    SYSTEM_LIVE_DATA_SOURCE: Literal["broker", "simulated"] = "broker"
    SYSTEM_LIVE_ALLOWED_HOSTS: list[str] = Field(default_factory=list)
    SYSTEM_LIVE_CREDENTIALS: Annotated[dict[str, LiveCredential], NoDecode] = Field(
        default_factory=dict
    )
    SYSTEM_LIVE_SOCKS_PROXIES: Annotated[dict[str, LiveSocksProxy], NoDecode] = Field(
        default_factory=dict, max_length=128
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

    @field_validator("SYSTEM_LIVE_SOCKS_PROXIES")
    @classmethod
    def exact_proxy_routes(cls, proxies: dict[str, LiveSocksProxy]):
        from off_key_core.schemas.system import SystemConnection

        return {
            SystemConnection(id="validation", label="Broker", host=host).host: proxy
            for host, proxy in proxies.items()
        }

    @field_validator("SYSTEM_LIVE_ALLOWED_HOSTS")
    @classmethod
    def exact_hosts(cls, hosts: list[str]) -> list[str]:
        from off_key_core.schemas.system import SystemConnection

        return [
            SystemConnection(id="validation", label="Broker", host=host).host
            for host in hosts
        ]

    def allows_host(self, host: str) -> bool:
        return host in self.SYSTEM_LIVE_ALLOWED_HOSTS

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
