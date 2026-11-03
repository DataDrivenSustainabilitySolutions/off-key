"""Reporting reads and pool backpressure against migrated TimescaleDB."""

import pytest
from off_key_core.db.base import get_async_engine, reset_db_runtime_caches
from off_key_core.db.migrate import apply_migrations
from off_key_tactic_middleware.main import create_app
from sqlalchemy import event

from tests.support.http import asgi_client


@pytest.mark.asyncio
async def test_report_reads_bounded_catalogue_history_and_recovers_from_busy_pool(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        connection.exec_driver_sql("""
            INSERT INTO chargers (charger_id, online, mqtt_connected, mqtt_error_count)
            VALUES ('busy', true, false, 0), ('quiet', false, false, 0),
                   ('removed', false, false, 0);
            INSERT INTO collection_bindings (charger_id, source_id, local_id)
            VALUES ('busy', 'source', 'busy'), ('quiet', 'source', 'quiet');
            INSERT INTO anomalies
                (charger_id, timestamp, telemetry_type, anomaly_type, anomaly_value)
            SELECT entity, now() - age * interval '1 second', 'temperature',
                   'test alarm', age
            FROM (VALUES ('busy', 501), ('quiet', 1), ('removed', 1))
                 AS inputs(entity, n)
            CROSS JOIN LATERAL generate_series(1, n) AS age;
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

    engine = get_async_engine()
    selects = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT"):
            selects.append(statement)

    headers = {"X-Off-Key-Service-Key": secret}
    path = "/api/v1/data/anomalies"
    try:
        async with asgi_client(create_app()) as client:
            async with engine.connect():
                unavailable = await client.get(path, headers=headers)
                assert unavailable.status_code == 503
                assert "Try again" in unavailable.json()["detail"]

            response = await client.get(path, headers=headers)
            assert response.status_code == 200
            assert len(selects) == 1
            rows = response.json()
            assert {row["charger_id"] for row in rows} == {"busy", "quiet"}
            assert {
                row["anomaly_value"] for row in rows if row["charger_id"] == "busy"
            } == set(range(1, 501))
            assert len({row["anomaly_id"] for row in rows}) == len(rows) == 501

            quiet = await client.get(f"{path}/quiet", headers=headers)
            assert quiet.status_code == 200
            assert quiet.json() == [row for row in rows if row["charger_id"] == "quiet"]
    finally:
        await engine.dispose()
        reset_db_runtime_caches()
