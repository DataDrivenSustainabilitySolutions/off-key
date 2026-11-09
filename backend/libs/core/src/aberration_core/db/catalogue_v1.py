"""Frozen v1 catalogue conversion, used only by the one-time database upgrade."""

import json
import re

from ..schemas.system import (
    SystemConnection,
    SystemDevice,
    SystemDocument,
    SystemGroup,
    SystemStream,
)
from .catalogue_v1_models import AmbiboxCatalog


def legacy_stream_id(charger_id: str, key: str) -> str:
    """Match the existing spatial catalog ID algorithm, including UTF-16 hashes."""
    prefix = f"ambibox:sensor:{charger_id}:"
    if re.fullmatch(r"[\w.-]+", key, flags=re.ASCII) and len(prefix + key) <= 128:
        return prefix + key
    value = json.dumps([charger_id, key], ensure_ascii=False, separators=(",", ":"))
    encoded = value.encode("utf-16-le")
    first, second = 0x811C9DC5, 0x9E3779B9
    for offset in range(0, len(encoded), 2):
        code = int.from_bytes(encoded[offset : offset + 2], "little")
        first = ((first ^ code) * 0x01000193) & 0xFFFFFFFF
        second = ((second ^ code) * 0x85EBCA6B) & 0xFFFFFFFF
        second ^= second >> 13
    return f"{prefix}key-{first:08x}{second:08x}"


def adapt_ambibox_catalog(catalog: AmbiboxCatalog) -> SystemDocument:
    connections, devices, streams, groups = [], [], [], []
    for source in catalog.sources:
        connection_id = f"ambibox:broker:{source.id}"
        connections.append(
            SystemConnection(
                id=connection_id,
                label=source.label,
                host=source.host,
                port=source.port,
            )
        )
        for charger_index, charger in enumerate(source.chargers):
            device_id = f"ambibox:charger:{charger.id}"
            devices.append(
                SystemDevice(
                    id=device_id,
                    label=charger.label,
                    connection_id=connection_id,
                    kind="charger",
                )
            )
            member_ids = [device_id]
            if charger_index == 0:
                member_ids.insert(0, connection_id)
            for sensor in charger.sensors:
                stream_id = legacy_stream_id(str(charger.id), sensor.key)
                member_ids.append(stream_id)
                streams.append(
                    SystemStream(
                        id=stream_id,
                        label=sensor.label,
                        connection_id=connection_id,
                        device_id=device_id,
                        topic=sensor.upstream_topic,
                        value_type=sensor.value_type,
                        unit=sensor.unit,
                        category=sensor.category,
                        policy=sensor.policy
                        or charger.policy
                        or catalog.default_policy,
                    )
                )
            groups.append(
                SystemGroup(
                    id=f"ambibox:group:{charger.id}",
                    label=charger.label,
                    member_ids=member_ids,
                )
            )
    return SystemDocument(
        label="Saved system",
        default_policy=catalog.default_policy,
        connections=connections,
        devices=devices,
        streams=streams,
        groups=groups,
    )
