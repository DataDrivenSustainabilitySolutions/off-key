"""Keep database values out of messages and chained exception diagnostics."""

import copy
import logging
import re
import traceback

from sqlalchemy.exc import SQLAlchemyError

_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "correlation_id",
}


def _database_error(error: BaseException | None) -> BaseException | None:
    seen: set[int] = set()
    pending = [error] if error is not None else []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, SQLAlchemyError) or type(current).__module__.startswith(
            ("asyncpg.", "psycopg2.")
        ):
            return current
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        pending.extend(
            linked
            for linked in (current.__cause__, current.__context__)
            if linked is not None
        )
    return None


def safe_error_text(error: BaseException) -> str:
    """Sanitize diagnostics before storing them outside an exception record."""
    database_error = _database_error(error)
    if database_error is not None:
        return f"{type(database_error).__name__}: database details redacted"
    return str(error)


def safe_database_record(record: logging.LogRecord) -> logging.LogRecord:
    """Preserve event identity and stack locations, never driver DETAIL text.

    hide_parameters protects SQLAlchemy's parameter list; PostgreSQL can also
    repeat a value in its error text, including in an exception's cause.
    """
    error = _database_error(record.exc_info[1]) if record.exc_info else None
    args = record.args.values() if isinstance(record.args, dict) else record.args
    for arg in args or ():
        if isinstance(arg, BaseException):
            error = error or _database_error(arg)
    if error is None:
        return record
    safe = copy.copy(record)
    event = re.match(r"event=[a-zA-Z0-9_.]+", str(record.msg))
    safe.msg = "%s error_type=%s database_details=redacted"
    safe.args = (event[0] if event else "event=database.error", type(error).__name__)
    # Extras may hold copies of driver text or parameters under arbitrary keys.
    # Keep the event and standard tracing fields, without retaining those copies.
    for key in safe.__dict__.keys() - _RECORD_FIELDS:
        safe.__dict__[key] = "[DATABASE DETAILS REDACTED]"
    safe.exc_info = None
    safe.exc_text = None
    if record.exc_info and record.exc_info[2]:
        safe.exc_text = (
            "\n".join(
                f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
                for frame in traceback.extract_tb(record.exc_info[2])
            )
            + f"\n{type(error).__name__}: database details redacted"
        )
    return safe
