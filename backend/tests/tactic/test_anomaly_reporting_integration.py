"""Reporting queries and pool backpressure against migrated TimescaleDB."""

from datetime import UTC, datetime, timedelta

import pytest
from aberration_core.db.base import get_async_engine, reset_db_runtime_caches
from aberration_core.db.migrate import apply_migrations
from aberration_core.schemas.system import SystemDocument, SystemRuntime, SystemSnapshot
from aberration_tactic_middleware.main import create_app
from aberration_tactic_middleware.services.catalogue.system import SystemService
from sqlalchemy import event

from tests.support.http import asgi_client

CATALOGUE = SystemSnapshot(
    revision=1,
    storage_origin="saved",
    document=SystemDocument(
        connections=[{"id": "broker", "label": "Plant MQTT", "host": "broker"}],
        devices=[{"id": "line", "label": "Line 1", "connection_id": "broker"}],
        streams=[
            {
                "id": key,
                "label": label,
                "connection_id": "broker",
                "device_id": "line",
                "topic": f"line/{key}",
            }
            for key, label in (("temperature", "Temperature"), ("pressure", "Pressure"))
        ]
        + [
            {
                "id": "quiet-temperature",
                "label": "Hall temperature",
                "connection_id": "broker",
                "topic": "hall/temperature",
            }
        ],
    ),
    runtime=SystemRuntime(
        bindings={
            "temperature": {"entity_id": "busy", "telemetry_key": "temperature"},
            "pressure": {"entity_id": "busy", "telemetry_key": "pressure"},
            "quiet-temperature": {"entity_id": "quiet", "telemetry_key": "temperature"},
        }
    ),
)


@pytest.mark.asyncio
async def test_reporting_queries_alarms_by_reading_and_recovers_from_busy_pool(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.exec_driver_sql("""
            INSERT INTO anomalies
                (charger_id, timestamp, telemetry_type, anomaly_type, anomaly_value)
            SELECT entity, now() - age * interval '1 second', 'temperature',
                   'test alarm', age
            FROM (VALUES ('busy', 501), ('quiet', 1), ('removed', 1))
                 AS inputs(entity, n)
            CROSS JOIN LATERAL generate_series(1, n) AS age;
            -- A day old: older than every row above, but inside the 14-day
            -- retention window, so the database's retention job cannot delete
            -- them while the test runs.
            INSERT INTO anomalies
                (charger_id, timestamp, telemetry_type, service_id, anomaly_type,
                 anomaly_value, value_type, sensor_set)
            VALUES
                ('busy', now() - interval '1 day', '__multivariate__', 'monitor-b',
                 'ml_conformal_static_x', 0.0005, 'conformal_pvalue',
                 '["temperature", "pressure"]'),
                ('busy', now() - interval '1 day' + interval '1 second',
                 '__multivariate__', 'monitor-c',
                 'ml_tailprob_x', 0.002, 'tail_pvalue', NULL),
                ('busy', now() - interval '1 day' + interval '2 seconds', 'pressure',
                 'monitor-a',
                 'ml_conformal_static_x', 0.02, 'conformal_pvalue', 'null');
        """)

    url = disposable_database.url
    secret = "disposable-reporting-integration-credential"
    for key, value in {
        "POSTGRES_USER": url.username,
        "POSTGRES_PASSWORD": url.password,
        "POSTGRES_DB": url.database,
        "POSTGRES_PORT": url.port or 5432,
        "POSTGRES_HOST": url.host,
        "POSTGRES_ASYNC_POOL_SIZE": 1,
        "POSTGRES_ASYNC_MAX_OVERFLOW": 0,
        "POSTGRES_ASYNC_POOL_TIMEOUT_SECONDS": 0.1,
        "INTERNAL_API_SECRET": secret,
    }.items():
        monkeypatch.setenv(key, str(value))

    async def catalogue(self):
        return CATALOGUE

    monkeypatch.setattr(SystemService, "read", catalogue)
    engine = get_async_engine()
    selects = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            selects.append(statement)

    headers = {"X-Aberration-Service-Key": secret}
    path = "/api/v1/data/alarms/query"
    line = ["temperature", "pressure"]
    try:
        async with asgi_client(create_app()) as client:

            async def query(**body):
                response = await client.post(path, headers=headers, json=body)
                assert response.status_code == 200, response.text
                return response.json()

            async with engine.connect():
                unavailable = await client.post(path, headers=headers, json={})
                assert unavailable.status_code == 503
                assert "Try again" in unavailable.json()["detail"]

            # One reading: its own alarms and multivariate alarms that used it,
            # paged newest first without gaps or repeats.
            seen, before = [], None
            while True:
                page = await query(reading_ids=["temperature"], before=before)
                seen += page["items"]
                before = page["next"]
                if before is None:
                    break
            assert page["summary"]["count"] == len(seen) == 502
            assert len({item["alarm_id"] for item in seen}) == 502
            assert [item["timestamp"] for item in seen] == sorted(
                (item["timestamp"] for item in seen), reverse=True
            )
            assert seen[-1]["multivariate"] is True
            assert seen[-1]["reading_ids"] == ["temperature", "pressure"]
            assert seen[-1]["reading_labels"] == {
                "temperature": "Temperature",
                "pressure": "Pressure",
            }
            assert (seen[0]["device_id"], seen[0]["device_label"]) == ("line", "Line 1")
            assert seen[0]["reading_labels"] == {"temperature": "Temperature"}

            # The whole entity also takes the multivariate alarm without a set.
            whole = await query(reading_ids=line, limit=1)
            assert whole["summary"] == {
                "count": 504,
                "devices": 1,
                "latest": whole["items"][0]["timestamp"],
            }
            assert [
                (item["reading_id"], item["label"], item["count"])
                for item in whole["readings"]
            ] == [("pressure", "Pressure", 2), ("temperature", "Temperature", 502)]
            assert {item["device_id"] for item in whole["readings"]} == {"line"}

            narrowed = {
                "p-value": {"max_p_value": 0.001},
                "monitor": {"monitor_id": "monitor-a"},
                "reading": {"reading_id": "pressure"},
                "time": {"since": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
            }
            counts = {}
            for name, body in narrowed.items():
                result = await query(reading_ids=line, **body)
                counts[name] = result["summary"]["count"]
                assert result["readings"] == whole["readings"]
            assert counts == {"p-value": 1, "monitor": 1, "reading": 2, "time": 501}

            unknown = await query(reading_ids=["gone"])
            assert unknown["items"] == [] and unknown["unknown_reading_ids"] == ["gone"]
            narrowed_away = await query(reading_ids=line, reading_id="gone")
            assert narrowed_away["summary"]["count"] == 0
            assert narrowed_away["unknown_reading_ids"] == ["gone"]

            selects.clear()
            everything = await query(limit=1)
            assert len(selects) == 3
            assert everything["summary"]["devices"] == 3
            # The alarms of an entity the catalogue no longer has name no device.
            removed = await client.get(
                "/api/v1/data/alarms", headers=headers, params={"limit": 1000}
            )
            assert removed.status_code == 200, removed.text
            orphans = [
                item["device_label"]
                for item in removed.json()
                if item["device_id"] is None
            ]
            assert sorted(orphans, key=str) == [None, "Plant MQTT"]
            device = await client.get(
                "/api/v1/data/alarms",
                headers=headers,
                params={"device_id": "line", "service_id": "monitor-c"},
            )
            assert [item["monitor_id"] for item in device.json()] == ["monitor-c"]
            assert everything["summary"]["count"] == 506
    finally:
        await engine.dispose()
        reset_db_runtime_caches()
