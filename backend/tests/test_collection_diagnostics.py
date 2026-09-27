from datetime import UTC, datetime
from types import SimpleNamespace

from off_key_mqtt_proxy import collection_diagnostics as diagnostics_module
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_mqtt_proxy.collection_diagnostics import CollectionDiagnostics
from off_key_mqtt_proxy.telemetry_models import WriteBatch, WriteStatus

from .test_collection import catalog, message


def test_rates_measure_wall_time_and_recover_after_old_errors(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(diagnostics_module.time, "monotonic", lambda: clock[0])
    buffer = CollectionBuffer(original_capacity=3)
    configuration = catalog("original")
    buffer.configure(configuration, now=0)
    writer = SimpleNamespace(
        total_records_written=0,
        last_successful_write_at=None,
        pending_batch=WriteBatch(),
        processing_batches={},
        batch_size=5,
    )
    diagnostics = CollectionDiagnostics(buffer, writer)
    assert diagnostics.snapshot(connected=True)["rates"]["received"] is None
    for value in range(10):
        buffer.receive(message(configuration, value))
    buffer.receive(message(configuration, "invalid"))
    buffer.take(now=10)
    writer.total_records_written = 2
    clock[0] = 10
    report = diagnostics.snapshot(connected=True)
    assert report["rates"] == {
        "received": 1.1,
        "accepted": 0.3,
        "invalid": 0.1,
        "overload_dropped": 0.7,
        "written": 0.2,
    }
    assert report["last_received_at"] is not None
    assert report["last_database_write_at"] is None
    writer.last_successful_write_at = datetime(2026, 9, 27, tzinfo=UTC)
    diagnostics.last_state_write_at = datetime(2026, 9, 28, tzinfo=UTC)
    writer.processing_batches["retry"] = WriteBatch(status=WriteStatus.FAILED)
    clock[0] = 50
    report = diagnostics.snapshot(connected=False)
    assert all(value == 0 for value in report["rates"].values())
    assert report["database_retrying"] and not report["mqtt_connected"]
    assert (
        report["last_database_write_at"] == diagnostics.last_state_write_at.isoformat()
    )
    assert buffer.metrics()["overload_dropped"] == 7  # lifetime count stays available


def test_diagnostics_sampling_memory_is_bounded_under_frequent_polling(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(diagnostics_module.time, "monotonic", lambda: clock[0])
    writer = SimpleNamespace(
        total_records_written=0,
        last_successful_write_at=None,
        pending_batch=WriteBatch(),
        processing_batches={},
        batch_size=5,
    )
    diagnostics = CollectionDiagnostics(CollectionBuffer(), writer)
    for tick in range(10000):
        clock[0] = tick / 100
        report = diagnostics.snapshot(connected=True)
    assert len(diagnostics._samples) <= 32
    assert 30 <= report["window_seconds"] <= 31
