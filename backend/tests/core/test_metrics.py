"""Prometheus metrics: a private port, route templates as labels, scrape-time state."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from off_key_core import metrics
from off_key_core.config import bootstrap
from off_key_mqtt_proxy.metrics import CollectionCollector
from off_key_mqtt_radar.pool.metrics import PoolCollector
from prometheus_client import CollectorRegistry, generate_latest


@pytest.mark.parametrize("raw", ["", "0", " "])
def test_metrics_stay_off_without_a_port(monkeypatch, raw):
    monkeypatch.setenv(metrics.METRICS_PORT_ENV, raw)
    assert metrics.metrics_port() is None


@pytest.mark.parametrize("raw", ["metrics", "80", "70000", "-1"])
def test_metrics_port_must_be_an_unprivileged_port(monkeypatch, raw):
    monkeypatch.setenv(metrics.METRICS_PORT_ENV, raw)
    with pytest.raises(ValueError, match="METRICS_PORT"):
        metrics.metrics_port()


def test_only_entry_points_that_ask_serve_metrics(monkeypatch):
    started = []
    monkeypatch.setattr(bootstrap, "load_env", lambda: None)
    monkeypatch.setattr(bootstrap, "load_yaml_config", lambda path: None)
    monkeypatch.setattr(
        bootstrap, "log_startup_logging_configuration", lambda name: None
    )
    monkeypatch.setattr(bootstrap, "start_metrics_server", started.append)
    bootstrap.start_service("child", None, [], context="test")
    assert started == []
    bootstrap.start_service("parent", None, [], context="test", metrics=True)
    assert started == ["parent"]


@pytest.mark.asyncio
async def test_requests_are_labelled_by_route_template_not_raw_path():
    app = FastAPI()

    @app.get("/v1/monitors/{monitor_id}")
    async def monitor(monitor_id: str):
        return {"id": monitor_id}

    app.add_middleware(metrics.HttpMetricsMiddleware, service="metrics-test")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/v1/monitors/a1")).status_code == 200
        assert (await client.get("/v1/monitors/b2")).status_code == 200
        assert (await client.get("/nowhere")).status_code == 404

    def count(route, status):
        return metrics.HTTP_REQUESTS.labels(
            "metrics-test", "GET", route, status
        )._value.get()

    assert count("/v1/monitors/{monitor_id}", "2xx") == 2
    assert count("unmatched", "4xx") == 1
    exposition = generate_latest().decode()
    assert "/v1/monitors/a1" not in exposition


def scrape(collector) -> str:
    registry = CollectorRegistry()
    registry.register(collector)
    return generate_latest(registry).decode()


def test_collection_metrics_read_the_proxy_state_on_scrape():
    service = SimpleNamespace(
        buffer=SimpleNamespace(
            metrics=lambda: {"received": 7, "accepted": 5, "original_queue": 2}
        ),
        database_writer=SimpleNamespace(
            total_records_written=5,
            total_batches_processed=2,
            total_batches_failed=0,
            queued_records=1,
            queue_capacity=1000,
            is_retrying=False,
            last_successful_write_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        mqtt_client=SimpleNamespace(is_connected=True),
        revision=3,
    )
    text = scrape(CollectionCollector(service))
    assert "offkey_collection_received_total 7.0" in text
    assert "offkey_collection_invalid_total 0.0" in text
    assert "offkey_collection_written_records_total 5.0" in text
    assert "offkey_collection_broker_connected 1.0" in text
    assert "offkey_collection_revision 3.0" in text
    assert "offkey_collection_last_write_timestamp_seconds 1.7672256e+09" in text


def test_pool_metrics_report_children_by_kind_and_crashes():
    finished = SimpleNamespace(returncode=0, pid=-1)
    pool = SimpleNamespace(
        children={
            "a": SimpleNamespace(kind="monitor", process=finished),
            "b": SimpleNamespace(kind="monitor", process=finished),
        },
        options=SimpleNamespace(kinds=("monitor", "preflight"), capacity=8),
        healthy=True,
        last_renewed=0.0,
        crashes=1,
        memory_kills=0,
    )
    text = scrape(PoolCollector(pool))
    assert 'offkey_radar_pool_children{kind="monitor"} 2.0' in text
    assert 'offkey_radar_pool_children{kind="preflight"} 0.0' in text
    assert "offkey_radar_pool_capacity 8.0" in text
    assert "offkey_radar_pool_crashes_total 1.0" in text
