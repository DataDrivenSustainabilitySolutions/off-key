import ipaddress
from functools import lru_cache
from typing import cast

from fastapi import Request, Response
from pydantic_settings import BaseSettings, SettingsConfigDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded


class ProxySettings(BaseSettings):
    """Networks whose X-Forwarded-For entries the gateway accepts."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    # The gateway is reachable only through Traefik/nginx on private overlay
    # networks; anything outside these ranges is treated as the client itself.
    TRUSTED_PROXY_CIDRS: tuple[str, ...] = (
        "127.0.0.0/8",
        "::1/128",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "fc00::/7",
    )


@lru_cache(maxsize=1)
def trusted_proxy_networks() -> tuple[
    ipaddress.IPv4Network | ipaddress.IPv6Network, ...
]:
    return tuple(
        ipaddress.ip_network(cidr, strict=False)
        for cidr in ProxySettings().TRUSTED_PROXY_CIDRS
    )


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(address in network for network in trusted_proxy_networks())


def client_ip(request: Request) -> str:
    """Return the nearest untrusted hop, so spoofed left-most entries are ignored."""
    peer = request.client.host if request.client else ""
    address = _parse_ip(peer)
    if address is None or not _is_trusted(address):
        return peer or "unknown"
    hops = [
        hop
        for header in request.headers.getlist("x-forwarded-for")
        for hop in header.split(",")
    ]
    for hop in reversed(hops):
        forwarded = _parse_ip(hop)
        if forwarded is None:
            break
        address = forwarded
        if not _is_trusted(forwarded):
            break
    return str(address)


limiter = Limiter(key_func=client_ip)


def rate_limit_exceeded_handler(request: Request, exc: Exception) -> Response:
    # Registered for status 429, which only the limiter raises.
    return _rate_limit_exceeded_handler(request, cast(RateLimitExceeded, exc))
