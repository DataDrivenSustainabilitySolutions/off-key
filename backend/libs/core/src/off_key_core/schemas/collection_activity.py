"""Current receipt activity, independent of the historical entity contact flag."""

from datetime import UTC, datetime
from math import isfinite

from .collection_status import is_applied
from .system import SystemRuntime


def _recent(value, now: datetime, seconds: float) -> bool:
    try:
        at = datetime.fromisoformat(value)
        age = (now - at.replace(tzinfo=at.tzinfo or UTC)).total_seconds()
        return -300 <= age < seconds
    except (TypeError, ValueError):
        return False


def reading_is_receiving(
    runtime: SystemRuntime, reading_id: str, now: datetime
) -> bool:
    revision = runtime.collection_revision
    if runtime.mode != "collection" or not all(
        is_applied(state, revision) and _recent(state.get("checked_at"), now, 30)
        for state in (runtime.collection, runtime.ingress)
    ):
        return False
    binding = runtime.bindings.get(reading_id, {})
    if binding.get("policy", {}).get("mode", "off") == "off":
        return False
    source = runtime.ingress.get("sources", {}).get(binding.get("broker_id"), {})
    if source.get("state") not in {"connected", "connecting", "reconnecting"}:
        return False
    receipt = runtime.ingress.get("readings", {}).get(reading_id, {})
    typical = receipt.get("typical_interval_seconds")
    typical = typical if isinstance(typical, int | float) and isfinite(typical) else 0
    # Same activity window as the catalogue UI: three usual gaps, 2-30 minutes.
    window = min(1800, max(120, 3 * typical))
    return _recent(receipt.get("fresh_received_at"), now, window)
