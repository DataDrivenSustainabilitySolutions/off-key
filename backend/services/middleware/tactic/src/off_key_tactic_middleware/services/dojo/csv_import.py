"""Read an uploaded CSV as a stream of (series name, timestamp, value) points.

Pure Python and streaming: a 100 MB upload is never held as parsed rows, so
the caller can copy points to the database in batches as they are read.
"""

import csv
import io
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from off_key_core.schemas.dojo import CsvImportQuery

from ...domain import ValidationError

DELIMITERS = (",", ";", "\t", "|")
# Epoch numbers this large are milliseconds; seconds reach it only in 5138.
MILLISECOND_EPOCH = 1e11


def detect_delimiter(header: str) -> str:
    counts = {delimiter: header.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=lambda delimiter: counts[delimiter])
    return best if counts[best] else ","


def parse_timestamp(text: str) -> datetime:
    """ISO 8601 or Unix epoch seconds/milliseconds; no zone means UTC."""
    text = text.strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        if not math.isfinite(number):
            raise ValueError("not a finite epoch time")
        seconds = number / 1000 if abs(number) >= MILLISECOND_EPOCH else number
        return datetime.fromtimestamp(seconds, UTC)
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parse_value(text: str, *, decimal_comma: bool) -> float:
    if decimal_comma:
        text = text.replace(",", ".")
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("not a finite number")
    return value


def _column(header: list[str], name: str) -> int:
    folded = [column.strip().casefold() for column in header]
    try:
        return folded.index(name.strip().casefold())
    except ValueError:
        raise ValidationError(f"The CSV has no column named {name!r}") from None


def _cell(row: list[str], index: int) -> str:
    return row[index].strip() if index < len(row) else ""


@dataclass(frozen=True)
class _Layout:
    """Where the timestamp, names and values sit in each row."""

    time_index: int
    # Wide: (series name, value column) pairs. Long: one pair of indexes.
    value_columns: tuple[tuple[str, int], ...] = ()
    series_index: int | None = None
    value_index: int | None = None

    def cells(self, row: list[str]) -> list[tuple[str, str]]:
        if self.series_index is None:
            return [(name, _cell(row, index)) for name, index in self.value_columns]
        return [(_cell(row, self.series_index), _cell(row, self.value_index))]


def _layout(header: list[str], query: CsvImportQuery) -> _Layout:
    if query.layout == "long":
        return _Layout(
            time_index=_column(header, query.timestamp_column or "timestamp"),
            series_index=_column(header, query.series_column),
            value_index=_column(header, query.value_column),
        )
    time_index = (
        _column(header, query.timestamp_column) if query.timestamp_column else 0
    )
    columns = tuple(
        (name.strip(), index)
        for index, name in enumerate(header)
        if index != time_index
    )
    names = [name for name, _ in columns]
    if not columns:
        raise ValidationError("A wide CSV needs at least one value column")
    if any(not name for name in names):
        raise ValidationError("Every value column needs a header name")
    if len(set(names)) != len(names):
        raise ValidationError("Value column names must be unique")
    return _Layout(time_index=time_index, value_columns=columns)


def _row_points(
    line: int, row: list[str], layout: _Layout, decimal_comma: bool
) -> Iterator[tuple[str, datetime, float]]:
    stamp = _cell(row, layout.time_index)
    try:
        timestamp = parse_timestamp(stamp)
    except (ValueError, OverflowError, OSError):
        raise ValidationError(
            f"Line {line}: {stamp!r} is not a timestamp "
            "(use ISO 8601 or Unix epoch time)"
        ) from None
    for name, cell in layout.cells(row):
        if not cell:
            continue
        if not name:
            raise ValidationError(f"Line {line}: the series name is empty")
        try:
            value = parse_value(cell, decimal_comma=decimal_comma)
        except ValueError:
            raise ValidationError(
                f"Line {line}: {cell!r} in {name!r} is not a finite number"
            ) from None
        yield name, timestamp, value


def read_points(
    body: bytes, query: CsvImportQuery
) -> tuple[list[str], Iterator[tuple[str, datetime, float]]]:
    """Return the declared series names and an iterator over the points.

    'wide' declares its value columns in order; 'long' declares none and
    names each series where it first appears. Empty cells are skipped.
    """
    try:
        text = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8-sig", newline="")
        first = text.readline()
    except UnicodeDecodeError:
        raise ValidationError("The CSV must be UTF-8 text") from None
    if not first.strip():
        raise ValidationError("The CSV is empty")
    delimiter = query.delimiter or detect_delimiter(first)
    header = next(csv.reader([first], delimiter=delimiter))
    layout = _layout(header, query)
    decimal_comma = delimiter != ","

    def points() -> Iterator[tuple[str, datetime, float]]:
        try:
            for line, row in enumerate(csv.reader(text, delimiter=delimiter), start=2):
                if any(cell.strip() for cell in row):
                    yield from _row_points(line, row, layout, decimal_comma)
        except UnicodeDecodeError:
            raise ValidationError("The CSV must be UTF-8 text") from None
        except csv.Error as exc:
            raise ValidationError(f"The CSV could not be read: {exc}") from None

    return [name for name, _ in layout.value_columns], points()
