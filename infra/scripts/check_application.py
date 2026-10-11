"""Read-only deployment probe, run inside the deployed MQTT proxy container."""

import asyncio
import json
import os
from datetime import datetime, timezone
from urllib.request import urlopen


def check_collection(snapshot, now, ingress_enabled=True, *, generic=False):
    selected = list(snapshot.catalog.streams(selected_only=True))
    # Before the first UI save there is no configuration row to hold heartbeats.
    # The caller has still verified the live collector, APIs and database query.
    if snapshot.revision == 0 and not snapshot.catalog.sources:
        return {"revision": 0, "selected_sensors": 0}
    workers = {"collection": snapshot.collection}
    if ingress_enabled:
        workers["ingress"] = snapshot.ingress
    for name, state in workers.items():
        if (
            state.get("revision") != snapshot.revision
            or state.get("status") != "applied"
        ):
            raise ValueError(
                f"{name} has not applied catalog revision {snapshot.revision}"
            )
        checked_at = datetime.fromisoformat(state.get("checked_at", ""))
        if not 0 <= (now - checked_at).total_seconds() <= 30:
            raise ValueError(f"{name} heartbeat is stale")
    if selected and not ingress_enabled:
        raise ValueError("Readings are selected but collection ingress is disabled")
    sources = {str(source.id): source for source in snapshot.catalog.sources}
    for source_id in sorted({str(stream.source_id) for stream in selected}):
        source = sources[source_id]
        broker = f"{source.label} ({source.host}:{source.port})"
        state = snapshot.ingress.get("sources", {}).get(source_id, {})
        # Generic ingress owns its subscriptions directly. Legacy ingress uses
        # applied GOST routes. An unavailable upstream is permitted in either
        # runtime, but a blocked/missing route must fail deployment verification.
        phase = state.get("state") if generic else state.get("status")
        allowed = (
            {"connected", "connecting", "waiting", "reconnecting"}
            if generic
            else {"connected", "connecting"}
        )
        if phase not in allowed or (
            not generic and state.get("configured") is not True
        ):
            raise ValueError(f"Selected broker {broker} has no applied ingress route")
        if phase != "connected":
            print(
                f"WARNING: Selected broker {broker} is not connected. "
                "Its ingress route is applied; connection retries continue automatically.",
                flush=True,
            )
    return {"revision": snapshot.revision, "selected_sensors": len(selected)}


async def main():
    from off_key_core.db.base import get_async_engine, get_async_session_local
    from off_key_core.db.collection_runtime import read_collection_runtime
    from off_key_core.schemas.system_collection import SystemCollectionDefinition

    endpoints = {
        "schema": "http://db-sync:8009/ready/schema",
        "api": "http://api:8000/health",
        "tactic": f"http://tactic:{os.environ.get('TACTIC_PORT', '8001')}/ready",
        "collector": "http://localhost:8010/ready",
    }
    for name, url in endpoints.items():
        with await asyncio.to_thread(urlopen, url, timeout=5) as response:
            json.load(response)
        print(f"{name}: ready", flush=True)
    try:
        async with get_async_session_local()() as session:
            snapshot = await read_collection_runtime(session)
        generic = isinstance(snapshot.catalog, SystemCollectionDefinition)
        ingress_setting = (
            "SYSTEM_COLLECTION_ENABLED" if generic else "AMBIBOX_INGRESS_ENABLED"
        )
        result = check_collection(
            snapshot,
            datetime.now(timezone.utc),
            os.environ.get(ingress_setting, "true").lower() == "true",
            generic=generic,
        )
        print(json.dumps(result))
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=30))
