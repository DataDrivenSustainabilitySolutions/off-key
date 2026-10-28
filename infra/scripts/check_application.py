"""Read-only deployment probe, run inside the deployed MQTT proxy container."""

import asyncio
import json
import os
from datetime import UTC, datetime
from urllib.request import urlopen

# States of an applied ingress route. Whether a source broker is reachable and accepts
# us is up to that broker, so a release reports these instead of failing: it cannot
# fix a broker, and holding the release open would block every later release.
BROKER_OUTCOMES = {"connected", "connecting", "waiting", "reconnecting", "error"}
ENDPOINTS = ("schema", "api", "tactic", "collector")
WORKERS = ("collection", "ingress")
# The only readiness output that may reach the public release log: fixed names that
# say which check failed, never a broker, host or message.
CHECKS = frozenset(
    {f"{name} endpoint" for name in ENDPOINTS}
    | {f"{name} {part}" for name in WORKERS for part in ("revision", "heartbeat")}
    | {
        "collection ingress disabled",
        "broker access",
        "broker route",
        "collector task",
        "probe timeout",
        "probe error",
    }
)
PUBLIC = "Failed readiness check: "


class NotReady(ValueError):
    """A failed readiness check: its public name, with private detail as message."""

    def __init__(self, check, detail):
        assert check in CHECKS
        super().__init__(detail)
        self.check = check


def check_collection(snapshot, now, ingress_enabled=True):
    selected = list(snapshot.catalog.streams(selected_only=True))
    # Before the first UI save there is no configuration row to hold heartbeats.
    # The caller has still verified the live collector, APIs and database query.
    if snapshot.revision == 0 and not snapshot.catalog.document.connections:
        return {"revision": 0, "selected_sensors": 0}
    workers = {"collection": snapshot.collection}
    if ingress_enabled:
        workers["ingress"] = snapshot.ingress
    for name, state in workers.items():
        if (
            state.get("revision") != snapshot.revision
            or state.get("status") != "applied"
        ):
            raise NotReady(
                f"{name} revision",
                f"{name} has not applied catalog revision {snapshot.revision}",
            )
        try:
            checked_at = datetime.fromisoformat(state.get("checked_at", ""))
        except ValueError:
            checked_at = None
        if checked_at is None or not 0 <= (now - checked_at).total_seconds() <= 30:
            raise NotReady(f"{name} heartbeat", f"{name} heartbeat is stale")
    if selected and not ingress_enabled:
        raise NotReady(
            "collection ingress disabled",
            "Readings are selected but collection ingress is disabled",
        )
    connections = snapshot.catalog.document.connections
    sources = {str(source.id): source for source in connections}
    for source_id in sorted({str(stream.source_id) for stream in selected}):
        source = sources[source_id]
        broker = f"{source.label} ({source.host}:{source.port})"
        state = snapshot.ingress.get("sources", {}).get(source_id, {})
        phase = state.get("state")
        if phase == "blocked":
            raise NotReady(
                "broker access",
                f"Selected broker {broker} has no broker access or credential "
                "in the operator configuration",
            )
        if phase not in BROKER_OUTCOMES:
            raise NotReady(
                "broker route", f"Selected broker {broker} has no applied ingress route"
            )
        if phase != "connected":
            print(
                f"WARNING: Selected broker {broker} is {phase}"
                f" ({state.get('message') or 'no detail reported'}). "
                "Its ingress route is applied; Sources shows how the broker answers.",
                flush=True,
            )
    return {"revision": snapshot.revision, "selected_sensors": len(selected)}


def probe_endpoints(environ):
    """Readiness URLs the deploy gate requires, keyed by service."""
    return {
        "schema": "http://db-sync:8009/ready/schema",
        "api": "http://api:8000/health",
        "tactic": f"http://tactic:{environ.get('TACTIC_PORT', '8001')}/ready",
        "collector": "http://localhost:8010/ready",
    }


def report(failure):
    """The public line naming a failed check; its detail stays on stderr."""
    if isinstance(failure, NotReady):
        return PUBLIC + failure.check
    if isinstance(failure, TimeoutError):
        return PUBLIC + "probe timeout"
    return PUBLIC + "probe error"


async def main():
    from off_key_core.db.base import get_async_engine, get_async_session_local
    from off_key_core.db.collection_runtime import read_collection_runtime

    for name, url in probe_endpoints(os.environ).items():
        try:
            with await asyncio.to_thread(urlopen, url, timeout=5) as response:
                json.load(response)
        except Exception as error:
            raise NotReady(
                f"{name} endpoint", f"{name} is not ready: {error}"
            ) from error
        print(f"{name}: ready", flush=True)
    try:
        async with get_async_session_local()() as session:
            snapshot = await read_collection_runtime(session)
        result = check_collection(
            snapshot,
            datetime.now(UTC),
            os.environ.get("SYSTEM_COLLECTION_ENABLED", "true").lower() == "true",
        )
        print(json.dumps(result))
    finally:
        await get_async_engine().dispose()


if __name__ == "__main__":
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=30))
    except Exception as failure:
        print(report(failure), flush=True)
        raise
