"""An optional operator-owned broker access adapter; never catalogue data."""

from dataclasses import dataclass

from ..config.system_live import LiveCredential, LiveSocksProxy


@dataclass(frozen=True)
class BrokerAccess:
    credential: LiveCredential | None = None
    proxy: LiveSocksProxy | None = None
    require_tls: bool = False
