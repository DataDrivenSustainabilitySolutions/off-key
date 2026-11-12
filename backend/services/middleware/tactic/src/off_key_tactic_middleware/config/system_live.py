"""Private operator controls for the sources TACTIC connects to: MQTT brokers
and polled HTTP APIs, for temporary observation and for recording."""

import base64
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

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


# Headers that frame a request; a credential may not replace them.
_FRAMING_HEADERS = {"connection", "content-length", "host", "transfer-encoding"}


class HttpCredential(BaseModel):
    """What an HTTP source expects in one request header: a basic login, a
    bearer token, or a key sent as written under a header of its own."""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(default="", max_length=512)
    password: SecretStr = SecretStr("")
    token: SecretStr = SecretStr("")
    header: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,64}$")

    @model_validator(mode="after")
    def one_login(self) -> Self:
        password = self.password.get_secret_value()
        token = self.token.get_secret_value()
        if bool(token) == bool(self.username or password):
            raise ValueError("Give a token, or a username and password")
        if self.header is not None and (
            not token or self.header.lower() in _FRAMING_HEADERS
        ):
            raise ValueError("A header of its own carries a token")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in f"{self.username}{password}{token}"
        ):
            raise ValueError("Credentials must not contain control characters")
        return self

    def request_header(self) -> tuple[str, str]:
        token = self.token.get_secret_value()
        if self.header is not None:
            return self.header, token
        if token:
            return "Authorization", f"Bearer {token}"
        login = f"{self.username}:{self.password.get_secret_value()}"
        return "Authorization", f"Basic {base64.b64encode(login.encode()).decode()}"


def _http_origin(value: str) -> str:
    """Normalise ``https://host[:port]`` to scheme, exact host and explicit port."""
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        port = 0
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
        or port == 0
    ):
        raise ValueError(
            "HTTP origins look like https://api.example.com or http://10.0.0.7:8080"
        )
    host = _exact_host(parts.hostname)
    port = port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{f'[{host}]' if ':' in host else host}:{port}"


class LiveSocksProxy(LiveCredential):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=1055, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def exact_proxy_host(cls, value: str) -> str:
        return _exact_host(value)


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
    # HTTP sources are polled with GET. An origin fixes scheme, host and port, so
    # a catalogue edit can neither reach another port nor drop TLS. Broker routes
    # and MQTT logins never apply to them.
    SYSTEM_HTTP_ALLOWED_ORIGINS: list[str] = Field(default_factory=list, max_length=128)
    SYSTEM_HTTP_CREDENTIALS: Annotated[dict[str, HttpCredential], NoDecode] = Field(
        default_factory=dict
    )
    # No request path is polled more often than this, whatever its readings ask.
    SYSTEM_HTTP_MIN_POLL_SECONDS: int = Field(default=1, ge=1, le=3600)

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
        "SYSTEM_LIVE_CREDENTIALS",
        "SYSTEM_LIVE_SOCKS_PROXIES",
        "SYSTEM_HTTP_CREDENTIALS",
        mode="before",
    )
    @classmethod
    def private_credentials(cls, value):
        return json.loads(value or "{}") if isinstance(value, str) else value

    @field_validator("SYSTEM_HTTP_ALLOWED_ORIGINS")
    @classmethod
    def exact_origins(cls, origins: list[str]) -> list[str]:
        return [_http_origin(origin) for origin in origins]

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

    def allows_origin(self, connection) -> bool:
        """Whether the operator listed this HTTP source's scheme, host and port."""
        host = f"[{connection.host}]" if ":" in connection.host else connection.host
        scheme = "https" if connection.tls else "http"
        origin = f"{scheme}://{host}:{connection.port}"
        return origin in self.SYSTEM_HTTP_ALLOWED_ORIGINS

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
