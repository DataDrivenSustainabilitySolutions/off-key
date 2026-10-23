"""UTC normalization shared by gateway cursors and telemetry parsing."""

from datetime import UTC, datetime, timedelta, timezone

from off_key_core.utils.timestamps import as_utc


def test_as_utc_reads_naive_values_as_utc():
    assert as_utc(datetime(2026, 1, 1, 12)) == datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_as_utc_converts_other_offsets():
    value = datetime(2026, 1, 1, 14, tzinfo=timezone(timedelta(hours=2)))

    converted = as_utc(value)

    assert converted == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert converted.tzinfo is UTC
