"""System status shows one server-side verdict on collection: the first failing
check, in the order the workers depend on each other."""

from datetime import UTC, datetime, timedelta
from typing import get_args

import pytest
from aberration_core.schemas.collection_health import DiagnosisCode, diagnose_collection

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def _healthy():
    checked = NOW.isoformat()
    return {
        "revision": 1,
        "collection": {
            "revision": 1,
            "status": "applied",
            "selected_sensors": 1,
            "checked_at": checked,
            "diagnostics": {
                "mqtt_connected": True,
                "window_seconds": 30,
                "rates": {
                    "received": 10,
                    "accepted": 0.1,
                    "invalid": 0,
                    "overload_dropped": 0,
                    "written": 0.1,
                },
                "database_retrying": False,
            },
        },
        "ingress": {
            "revision": 1,
            "status": "applied",
            "checked_at": checked,
            "sources": {"broker": {"state": "connected"}},
        },
    }


def _diagnose(state, now=NOW):
    return diagnose_collection(
        state["revision"], state["collection"], state["ingress"], now
    )


def _set(path, value):
    def change(state):
        *parents, key = path.split(".")
        target = state
        for part in parents:
            target = target[part]
        target[key] = value

    return change


CHECKS = [
    ("collecting", lambda state: None),
    ("not_configured", _set("revision", 0)),
    ("paused", _set("collection.selected_sensors", 0)),
    ("disconnected", _set("collection.diagnostics.mqtt_connected", False)),
    ("waiting_for_measurements", lambda state: state["collection"].pop("diagnostics")),
    ("collection_error", _set("collection.status", "error")),
    ("applying_changes", _set("collection.revision", 0)),
    ("broker_disconnected", _set("ingress.sources.broker.state", "connecting")),
    ("connected_but_quiet", _set("collection.diagnostics.rates.received", 0)),
    ("measuring_traffic", _set("collection.diagnostics.rates.received", None)),
    ("invalid_payloads", _set("collection.diagnostics.rates.invalid", 1)),
    ("overloaded", _set("collection.diagnostics.rates.overload_dropped", 1)),
    ("database_retrying", _set("collection.diagnostics.database_retrying", True)),
    (
        "worker_not_reporting",
        _set("collection.checked_at", (NOW - timedelta(minutes=1)).isoformat()),
    ),
    ("worker_not_reporting", lambda state: state["collection"].pop("checked_at")),
]

# The broker controller only matters once the collector has prepared a revision.
ROUTE_BLOCKERS = [
    ("ingress_disabled", _set("ingress.status", "disabled")),
    ("broker_routes_failed", _set("ingress.status", "error")),
    ("broker_routes_not_ready", _set("ingress.revision", 0)),
    (
        "broker_controller_not_reporting",
        _set("ingress.checked_at", datetime(1970, 1, 1, tzinfo=UTC).isoformat()),
    ),
]


@pytest.mark.parametrize(("code", "change"), CHECKS)
def test_the_first_failing_check_is_the_diagnosis(code, change):
    state = _healthy()
    change(state)
    assert _diagnose(state).code == code


@pytest.mark.parametrize(("code", "change"), ROUTE_BLOCKERS)
def test_a_prepared_collector_shows_what_blocks_the_broker_routes(code, change):
    state = _healthy()
    state["collection"]["status"] = "prepared"
    change(state)
    assert _diagnose(state).code == code


def test_failed_routes_explain_themselves_with_the_broker_error():
    state = _healthy()
    state["ingress"]["status"] = "error"
    state["ingress"]["sources"]["broker"]["error"] = "Broker refused the password"
    assert _diagnose(state).explanation == "Broker refused the password"
    state["ingress"]["error"] = "Route table could not be written"
    assert _diagnose(state).explanation == "Route table could not be written"


def test_errors_since_worker_start_are_not_a_current_overload():
    state = _healthy()
    state["collection"]["counters"] = {"overload_dropped": 500, "invalid": 20}
    assert _diagnose(state).code == "collecting"


def test_reports_tolerate_clock_skew_but_not_silence():
    state = _healthy()
    assert _diagnose(state, NOW - timedelta(seconds=4)).code == "collecting"
    assert _diagnose(state, NOW - timedelta(seconds=6)).code == "worker_not_reporting"
    assert _diagnose(state, NOW + timedelta(seconds=15)).code == "collecting"
    assert _diagnose(state, NOW + timedelta(seconds=16)).code == "worker_not_reporting"


def test_measurements_are_current_only_for_a_fresh_report_of_the_saved_revision():
    state = _healthy()
    assert _diagnose(state).measurements_current
    assert not _diagnose(state, NOW + timedelta(minutes=1)).measurements_current
    state["revision"] = 2
    assert not _diagnose(state).measurements_current


def test_every_code_is_reached_by_a_case():
    reached = {code for code, _ in CHECKS + ROUTE_BLOCKERS}
    assert reached == set(get_args(DiagnosisCode))
