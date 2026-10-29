"""Resolve operator-owned broker access once for live previews, ingress and saves."""

from dataclasses import dataclass
from typing import Literal

from off_key_core.schemas.system import SystemConnection

from ...config.system_live import LiveCredential, LiveSocksProxy, SystemLiveSettings


@dataclass(frozen=True)
class BrokerAccess:
    """An optional operator-owned access adapter; never catalogue data."""

    credential: LiveCredential | None = None
    proxy: LiveSocksProxy | None = None
    require_tls: bool = False


@dataclass(frozen=True)
class ResolvedBroker:
    connection: SystemConnection
    credential: LiveCredential | None
    proxy: LiveSocksProxy | None


BrokerBlock = Literal["host_not_allowed", "credential_missing"]


class BrokerRouteAccess:
    """Access through the operator's broker routes (SYSTEM_BROKER_ROUTES)."""

    def __init__(self, settings: SystemLiveSettings):
        self.settings = settings

    def __call__(self, connection: SystemConnection) -> BrokerAccess | None:
        route = self.settings.route_for(connection.host)
        # The SOCKS client tunnels plain MQTT over TCP only.
        if route is None or (route.socks_proxy and connection.transport != "tcp"):
            return None
        return BrokerAccess(
            credential=route.credential,
            proxy=route.socks_proxy,
            require_tls=route.require_tls,
        )


def resolve_broker(
    settings: SystemLiveSettings,
    connection: SystemConnection,
    access: BrokerAccess | None,
) -> ResolvedBroker | BrokerBlock:
    """Allowlisted or adapter-backed hosts only; named credentials must exist."""
    if not settings.allows_host(connection.host) and access is None:
        return "host_not_allowed"
    credential = settings.SYSTEM_LIVE_CREDENTIALS.get(connection.credential_ref)
    if connection.credential_ref and credential is None:
        return "credential_missing"
    if credential is None and access is not None:
        credential = access.credential
    proxy = settings.SYSTEM_LIVE_SOCKS_PROXIES.get(connection.host)
    if proxy is None and access is not None:
        proxy = access.proxy
    if access is not None and access.require_tls:
        connection = connection.model_copy(update={"tls": True})
    return ResolvedBroker(connection, credential, proxy)
