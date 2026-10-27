"""Load the public demo's committed source catalogue and start recording it.

The deployment pipes the catalogue document to standard input. It is loaded
once, into an installation that has no catalogue yet; after that the catalogue
belongs to the administrator, and deployments leave it as it is.
"""

import asyncio
import json
import sys

from off_key_core.config.env import load_env
from off_key_core.db.base import get_async_engine, get_async_session_local
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import SystemChange, SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionChange

from .services.catalogue.system import SystemService

ACTOR = "demo deployment"
# The open data feeds update about once a minute.
RECORDING = CollectionPolicy(mode="sample", interval_seconds=60)


async def seed(session, document: SystemDocument) -> dict:
    system = SystemService(session)
    if (await system.read()).storage_origin != "empty":
        return {"status": "kept"}
    saved = await system.save(
        SystemChange(expected_revision=0, document=document), actor=ACTOR
    )
    await system.apply_collection(
        SystemCollectionChange(
            expected_revision=saved.revision,
            expected_collection_revision=saved.runtime.collection_revision,
            stream_ids=[stream.id for stream in document.streams],
            policy=RECORDING,
        ),
        actor=ACTOR,
    )
    return {"status": "loaded", "readings": len(document.streams)}


async def main() -> None:
    load_env()
    document = SystemDocument.model_validate_json(sys.stdin.read())
    try:
        async with get_async_session_local()() as session:
            result = await seed(session, document)
            await session.commit()
        print(json.dumps(result))
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
