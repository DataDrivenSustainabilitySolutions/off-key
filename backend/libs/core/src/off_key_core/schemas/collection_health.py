"""One verdict on whether collection works, decided on the server.

The collector and TACTIC's ingress each store a raw status document. Reading
them takes an ordered set of checks (report age, revision, broker routes,
traffic), and the first failing check is what an operator should fix. Deciding
it here gives the web app and API clients the same answer instead of each
re-implementing the order.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..utils.timestamps import as_utc
from .collection_status import COLLECTION_APPLIED, COLLECTION_ERROR

DiagnosisCode = Literal[
    "not_configured",
    "worker_not_reporting",
    "waiting_for_measurements",
    "disconnected",
    "collection_error",
    "applying_changes",
    "paused",
    "ingress_disabled",
    "broker_controller_not_reporting",
    "broker_routes_failed",
    "broker_routes_not_ready",
    "broker_disconnected",
    "database_retrying",
    "overloaded",
    "invalid_payloads",
    "measuring_traffic",
    "connected_but_quiet",
    "collecting",
]
DiagnosisTone = Literal["positive", "warning", "danger", "neutral"]
Verdict = tuple[DiagnosisCode, str]

# Workers rewrite their report every few seconds; one older than this means the
# worker stopped. The small allowance into the future absorbs container clock skew.
REPORT_MAX_AGE = timedelta(seconds=15)
REPORT_MAX_SKEW = timedelta(seconds=5)

_PRESENTATION: dict[DiagnosisCode, tuple[str, DiagnosisTone]] = {
    "not_configured": ("Not configured", "neutral"),
    "worker_not_reporting": ("Worker not reporting", "danger"),
    "waiting_for_measurements": ("Waiting for measurements", "warning"),
    "disconnected": ("Disconnected", "danger"),
    "collection_error": ("Collection error", "danger"),
    "applying_changes": ("Applying changes", "warning"),
    "paused": ("Paused", "neutral"),
    "ingress_disabled": ("Ingress disabled", "neutral"),
    "broker_controller_not_reporting": ("Broker controller not reporting", "danger"),
    "broker_routes_failed": ("Broker routes failed", "danger"),
    "broker_routes_not_ready": ("Broker routes not ready", "warning"),
    "broker_disconnected": ("Broker disconnected", "danger"),
    "database_retrying": ("Database retrying", "warning"),
    "overloaded": ("Overloaded", "danger"),
    "invalid_payloads": ("Invalid payloads", "danger"),
    "measuring_traffic": ("Measuring traffic", "warning"),
    "connected_but_quiet": ("Connected but quiet", "warning"),
    "collecting": ("Collecting", "positive"),
}


class CollectionDiagnosis(BaseModel):
    code: DiagnosisCode = Field(
        description="Stable identifier of the first check that fails, "
        "or `collecting` when none does."
    )
    tone: DiagnosisTone = Field(
        description="`positive` collects, `danger` needs an operator, "
        "`warning` is transient or degraded, `neutral` is idle on purpose."
    )
    title: str = Field(description="Short label shown in System status.")
    explanation: str = Field(description="What it means and what to check next.")
    measurements_current: bool = Field(
        description="Whether the collector's rates and queues describe the "
        "saved revision now, rather than an old report."
    )
    checked_at: datetime = Field(description="When the server made this diagnosis.")


class CollectionHealth(BaseModel):
    revision: int = Field(
        description="Saved catalogue revision; 0 before the first save."
    )
    collection: dict[str, Any] = Field(
        description="The collector's latest report: revision, status, "
        "diagnostics (rates, queues) and counters since the worker started."
    )
    ingress: dict[str, Any] = Field(
        description="The broker controller's latest report: revision, status, "
        "generation and per-broker `sources` state."
    )
    diagnosis: CollectionDiagnosis


def report_is_fresh(state: Mapping[str, Any], now: datetime) -> bool:
    """Whether a worker wrote this report recently enough to trust it."""
    try:
        checked = as_utc(datetime.fromisoformat(state["checked_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return -REPORT_MAX_SKEW <= now - checked <= REPORT_MAX_AGE


def diagnose_collection(
    revision: int,
    collection: Mapping[str, Any],
    ingress: Mapping[str, Any],
    now: datetime | None = None,
) -> CollectionDiagnosis:
    """The first problem an operator should fix, in the order workers depend on."""
    now = now or datetime.now(UTC)
    code, explanation = _first_problem(revision, collection, ingress, now)
    title, tone = _PRESENTATION[code]
    return CollectionDiagnosis(
        code=code,
        tone=tone,
        title=title,
        explanation=explanation,
        measurements_current=report_is_fresh(collection, now)
        and collection.get("revision") == revision,
        checked_at=now,
    )


def _first_problem(
    revision: int,
    collection: Mapping[str, Any],
    ingress: Mapping[str, Any],
    now: datetime,
) -> Verdict:
    # Routes only matter once the collector runs, and traffic once routes exist.
    return (
        _collector_problem(revision, collection, now)
        or _route_problem(revision, collection, ingress, now)
        or _traffic_verdict(collection["diagnostics"])
    )


def _collector_problem(
    revision: int, collection: Mapping[str, Any], now: datetime
) -> Verdict | None:
    data = collection.get("diagnostics")
    if revision == 0:
        return (
            "not_configured",
            "Add a catalog and select sensors to start collecting.",
        )
    if not report_is_fresh(collection, now):
        return (
            "worker_not_reporting",
            "Collection status is stale. Check the collector and database connection.",
        )
    if not data:
        return (
            "waiting_for_measurements",
            "The worker has not reported diagnostics yet.",
        )
    if not data.get("mqtt_connected"):
        return (
            "disconnected",
            "The collector cannot reach the local MQTT broker.",
        )
    if collection.get("status") == COLLECTION_ERROR:
        return (
            "collection_error",
            collection.get("error")
            or "Check the collector logs and database connection.",
        )
    if collection.get("revision") != revision:
        return (
            "applying_changes",
            "Wait for the workers to apply the saved catalog.",
        )
    if (
        collection.get("selected_sensors") == 0
        and collection.get("status") == COLLECTION_APPLIED
    ):
        return (
            "paused",
            "No sensors are selected in the saved catalog. "
            "Enable sensors and apply the changes.",
        )
    return None


def _route_problem(
    revision: int,
    collection: Mapping[str, Any],
    ingress: Mapping[str, Any],
    now: datetime,
) -> Verdict | None:
    if ingress.get("status") == "disabled":
        return (
            "ingress_disabled",
            "The operator has disabled broker access.",
        )
    if not report_is_fresh(ingress, now):
        return (
            "broker_controller_not_reporting",
            "Route status is stale. Check TACTIC and its database connection.",
        )
    sources = (ingress.get("sources") or {}).values()
    if ingress.get("revision") == revision and ingress.get("status") == "error":
        source_error = next(
            (source["error"] for source in sources if source.get("error")), None
        )
        return (
            "broker_routes_failed",
            ingress.get("error")
            or source_error
            or "Check the broker controller, network and endpoint configuration.",
        )
    if ingress.get("revision") != revision or ingress.get("status") != "applied":
        return (
            "broker_routes_not_ready",
            ingress.get("error")
            or "The broker controller is applying the saved catalog.",
        )
    if collection.get("status") != COLLECTION_APPLIED:
        return (
            "applying_changes",
            "Wait for the collector to activate the saved catalog.",
        )
    if any(source.get("state") not in {"connected", "paused"} for source in sources):
        return (
            "broker_disconnected",
            "At least one selected broker is unavailable. "
            "Check its endpoint, network and credentials.",
        )
    return None


def _traffic_verdict(data: Mapping[str, Any]) -> Verdict:
    rates = data.get("rates") or {}
    if data.get("database_retrying"):
        return (
            "database_retrying",
            "Accepted measurements are waiting for the database. Queues are "
            "bounded; sustained pressure can drop new observations.",
        )
    if (rates.get("overload_dropped") or 0) > 0:
        return (
            "overloaded",
            "Recent traffic exceeded the original-rate queue. "
            "Increase sampling intervals or pause sensors.",
        )
    if (rates.get("invalid") or 0) > 0:
        return (
            "invalid_payloads",
            "Some recent messages do not match their catalog types or ingress "
            "format. Check the sensor definitions.",
        )
    if rates.get("received") is None:
        return (
            "measuring_traffic",
            "Waiting for the first rate measurement.",
        )
    if rates.get("received") == 0:
        return (
            "connected_but_quiet",
            "Connections are ready, but selected topics have no recent messages. "
            "Check the topics and whether the entities are sending.",
        )
    return (
        "collecting",
        "Selected messages are arriving. "
        "Sampling keeps only the newest observation per interval.",
    )
