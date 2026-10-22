"""Status documents the collection workers store on the configuration row.

The collector writes ``collection_status`` and TACTIC's ingress writes
``ingress_status``; each reads the other's to sequence a catalogue revision.
The shapes are for static typing only and are not validated at runtime.
"""

from collections.abc import Mapping
from typing import Any, TypedDict

COLLECTION_STARTING = "starting"
COLLECTION_DISABLED = "disabled"
COLLECTION_APPLYING = "applying"
COLLECTION_PREPARED = "prepared"
COLLECTION_APPLIED = "applied"
COLLECTION_ERROR = "error"

INGRESS_CONNECTING = "connecting"
INGRESS_APPLIED = "applied"


class CollectionDiagnosticsState(TypedDict, total=False):
    mqtt_connected: bool
    window_seconds: float
    rates: dict[str, float | None]
    last_received_at: str | None
    last_database_write_at: str | None
    original_queue: int
    original_capacity: int
    sample_slots: int
    database_queue: int
    database_capacity: int
    database_retrying: bool


class CollectionWorkerState(TypedDict, total=False):
    revision: int | None
    status: str
    selected_sensors: int
    idle: bool
    checked_at: str
    counters: dict[str, Any]
    records_written: int
    diagnostics: CollectionDiagnosticsState
    error: str


class IngressWorkerState(TypedDict, total=False):
    revision: int
    generation: str | None
    status: str
    sources: dict[str, dict[str, Any]]
    readings: dict[str, dict[str, Any]]
    checked_at: str
    last_publish_at: str | None
    dropped: int


def is_applied(state: Mapping[str, Any], revision: int) -> bool:
    """Whether a worker has fully applied this catalogue revision."""
    return (
        state.get("revision") == revision and state.get("status") == COLLECTION_APPLIED
    )


def is_prepared_or_applied(state: Mapping[str, Any], revision: int) -> bool:
    """Whether the collector listens for this revision's ingress generation."""
    return state.get("revision") == revision and state.get("status") in {
        COLLECTION_PREPARED,
        COLLECTION_APPLIED,
    }
