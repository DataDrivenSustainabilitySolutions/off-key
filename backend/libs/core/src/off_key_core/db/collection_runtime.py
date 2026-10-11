"""One admission runtime: generic configuration supersedes the legacy adapter."""

from dataclasses import dataclass

from sqlalchemy import select

from ..schemas.system_collection import SystemCollectionDefinition
from .collection import read_collection_configuration
from .system import SystemCollectionConfiguration


@dataclass
class CollectionRuntimeSnapshot:
    revision: int
    catalog: SystemCollectionDefinition
    ingress: dict
    collection: dict
    status_model: type = SystemCollectionConfiguration


async def read_collection_runtime(session):
    row = await session.scalar(
        select(SystemCollectionConfiguration).where(
            SystemCollectionConfiguration.id == 1
        )
    )
    if row is None:
        return await read_collection_configuration(session)
    return CollectionRuntimeSnapshot(
        revision=row.revision,
        catalog=SystemCollectionDefinition.model_validate(row.document),
        ingress=row.ingress_status,
        collection=row.collection_status,
    )
