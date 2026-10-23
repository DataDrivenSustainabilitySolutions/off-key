"""The sole, domain-neutral admission runtime."""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select

from ..schemas.collection_status import is_applied
from ..schemas.system import SystemDocument
from ..schemas.system_collection import SystemCollectionDefinition
from .system import SystemCollectionConfiguration


@dataclass
class CollectionRuntimeSnapshot:
    revision: int
    catalog: SystemCollectionDefinition
    ingress: dict
    collection: dict


async def read_collection_runtime(session):
    row = await session.scalar(
        select(SystemCollectionConfiguration).where(
            SystemCollectionConfiguration.id == 1
        )
    )
    if row is None:
        return CollectionRuntimeSnapshot(
            revision=0,
            catalog=SystemCollectionDefinition(document=SystemDocument(), bindings={}),
            ingress={},
            collection={},
        )
    return CollectionRuntimeSnapshot(
        revision=row.revision,
        catalog=SystemCollectionDefinition.model_validate(row.document),
        ingress=row.ingress_status,
        collection=row.collection_status,
    )


async def monitoring_collection_fingerprint(session, topics: list[str]) -> str:
    """Validate selected aligned inputs without touching Docker or ML runtimes."""
    collection = await read_collection_runtime(session)
    streams = {
        stream.accepted_topic: stream
        for stream in collection.catalog.streams(selected_only=True)
        if stream.value_type == "number"
    }
    if any(topic not in streams for topic in topics):
        raise ValueError(
            "Monitoring requires selected numeric sensors from the catalog"
        )
    if not is_applied(collection.collection, collection.revision):
        raise ValueError("Wait until the collection configuration is applied")
    return hashlib.sha256(
        json.dumps([streams[topic].signature for topic in sorted(topics)]).encode()
    ).hexdigest()
