"""Reuse the operator's existing vendor access for temporary MQTT previews."""

from urllib.parse import urlsplit

from off_key_core.schemas.system import SystemConnection

from ..config.collection import AmbiboxSettings
from ..config.system_live import LiveCredential, LiveSocksProxy
from .broker_access import BrokerAccess


class AmbiboxLiveAccess:
    def __init__(self, settings: AmbiboxSettings):
        self.settings = settings

    def __call__(self, connection: SystemConnection) -> BrokerAccess | None:
        settings = self.settings
        if (
            not settings.AMBIBOX_INGRESS_ENABLED
            or not settings.allows_host(connection.host)
            or connection.transport != "tcp"
        ):
            return None
        try:
            endpoint = urlsplit("socks5://" + settings.AMBIBOX_SOCKS_SERVER)
            proxy = LiveSocksProxy(
                host=endpoint.hostname or "", port=endpoint.port or 1055
            )
        except ValueError:
            return None
        if (
            not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.path
            or endpoint.query
            or endpoint.fragment
        ):
            return None
        return BrokerAccess(
            credential=LiveCredential(
                username=settings.AMBIBOX_MQTT_USERNAME,
                password=settings.AMBIBOX_MQTT_PASSWORD,
            ),
            proxy=proxy,
            require_tls=settings.AMBIBOX_MQTT_TLS,
        )
