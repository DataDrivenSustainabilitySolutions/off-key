"""Retire generated v1 EMQX/GOST routes; never create or adapt old routes."""

import asyncio
import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..config.collection import get_ambibox_settings

RESOURCE_PREFIX = "offkey_ambibox_"


class IngressError(Exception):
    pass


class ManagementApi:
    def __init__(self, url: str, username: str, password: str):
        self.url = url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}

    async def request(self, method: str, path: str, payload=None):
        def send():
            request = Request(
                f"{self.url}/{path.lstrip('/')}",
                method=method,
                data=None if payload is None else json.dumps(payload).encode(),
                headers={**self.headers, "Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=10) as response:
                    body = response.read(2 * 1024 * 1024 + 1)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("Management response exceeds limit")
                    return json.loads(body) if body else None
            except HTTPError as exc:
                if exc.code == 404 and (
                    method == "GET"
                    or (
                        method == "DELETE" and path.startswith("mqtt/retainer/message/")
                    )
                ):
                    return None
                # Broker API bodies can contain credentials or submitted configuration.
                raise IngressError(f"Management API returned HTTP {exc.code}") from None
            except (URLError, TimeoutError, ValueError) as exc:
                raise IngressError(
                    "Management API is unavailable or returned invalid data"
                ) from exc

        return await asyncio.to_thread(send)


async def retire_v1_ingress():
    settings = get_ambibox_settings()
    if not settings.AMBIBOX_EMQX_API_KEY.get_secret_value():
        return
    emqx = ManagementApi(
        settings.AMBIBOX_EMQX_API_URL,
        settings.AMBIBOX_EMQX_API_KEY.get_secret_value(),
        settings.AMBIBOX_EMQX_API_SECRET.get_secret_value(),
    )
    for collection in ("rules", "sources", "connectors"):
        entries = await _entries(emqx, collection)
        for entry in entries:
            name = entry.get("name", entry.get("id", ""))
            if name.startswith(RESOURCE_PREFIX):
                identity = name if collection == "rules" else f"mqtt:{name}"
                await emqx.request("DELETE", f"{collection}/{quote(identity, safe='')}")
    if settings.AMBIBOX_GOST_PASSWORD.get_secret_value():
        gost = ManagementApi(
            settings.AMBIBOX_GOST_API_URL,
            settings.AMBIBOX_GOST_USERNAME,
            settings.AMBIBOX_GOST_PASSWORD.get_secret_value(),
        )
        config = await gost.request("GET", "config") or {}
        for entry in config.get("services") or []:
            if entry["name"].startswith(RESOURCE_PREFIX):
                await gost.request(
                    "DELETE", "config/services/" + quote(entry["name"], safe="")
                )


async def _entries(emqx, collection):
    if collection != "rules":
        return await emqx.request("GET", collection) or []
    entries, page = [], 1
    while True:
        response = await emqx.request("GET", f"rules?page={page}&limit=100")
        entries.extend(response["data"])
        if not response["meta"]["hasnext"]:
            return entries
        page += 1
