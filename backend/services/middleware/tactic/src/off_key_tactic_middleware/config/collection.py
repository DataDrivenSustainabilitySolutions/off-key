"""Operator-provisioned access to the fixed AmbiBox provider."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AmbiboxSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    AMBIBOX_INGRESS_ENABLED: bool = False
    AMBIBOX_ALLOWED_HOST_SUFFIXES: list[str] = [".ts.net"]
    AMBIBOX_ALLOWED_HOSTS: list[str] = []
    AMBIBOX_EMQX_API_URL: str = "http://emqx-main:18083/api/v5"
    AMBIBOX_EMQX_API_KEY: SecretStr = SecretStr("")
    AMBIBOX_EMQX_API_SECRET: SecretStr = SecretStr("")
    AMBIBOX_GOST_API_URL: str = "http://mqtt-tailscale-bridge:18080"
    AMBIBOX_GOST_USERNAME: str = "off-key"
    AMBIBOX_GOST_PASSWORD: SecretStr = SecretStr("")
    AMBIBOX_FORWARD_HOST: str = "mqtt-tailscale-bridge"
    AMBIBOX_SOCKS_SERVER: str = "tailscale-ambibox:1055"
    AMBIBOX_MQTT_USERNAME: str = ""
    AMBIBOX_MQTT_PASSWORD: SecretStr = SecretStr("")
    AMBIBOX_MQTT_TLS: bool = False

    def allows_host(self, host: str) -> bool:
        return host in self.AMBIBOX_ALLOWED_HOSTS or any(
            host.endswith(suffix) and suffix.startswith(".")
            for suffix in self.AMBIBOX_ALLOWED_HOST_SUFFIXES
        )


@lru_cache(maxsize=1)
def get_ambibox_settings() -> AmbiboxSettings:
    return AmbiboxSettings()
