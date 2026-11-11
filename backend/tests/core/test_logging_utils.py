import io
import json
import logging
import logging.config
import sys
from contextlib import suppress
from pathlib import Path

import pytest
from off_key_core.config.logs import (
    JsonFormatter,
    KeyValueFormatter,
    TruncatingFormatter,
    _apply_log_format,
    _ensure_root_handlers,
    _expand_env_vars,
    load_yaml_config,
    redact_query_params,
)
from off_key_core.config.logs import (
    logger as core_logger,
)
from sqlalchemy.exc import IntegrityError


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="event=logging_test value=%s",
        args=("ok",),
        exc_info=None,
    )
    record.correlation_id = "cid-123"
    record.component = "unit-test"
    record.service = "core"

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "event=logging_test value=ok"
    assert payload["correlation_id"] == "cid-123"
    assert payload["extra"]["component"] == "unit-test"
    assert payload["extra"]["service"] == "core"
    assert "correlation_id" not in payload["extra"]


@pytest.mark.parametrize(
    "formatter", [JsonFormatter(), KeyValueFormatter("%(message)s")]
)
def test_database_errors_hide_parameters_and_driver_details_in_chains(formatter):
    secret = "synthetic-private-database-value"
    try:
        try:
            raise IntegrityError(
                "INSERT INTO users VALUES (?)",
                (secret,),
                ValueError(f"DETAIL: Key (email)=({secret}) already exists"),
                hide_parameters=True,
            )
        except IntegrityError as exc:
            raise RuntimeError(f"database failed: {exc}") from exc
    except RuntimeError as exc:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            __file__,
            1,
            f"event=database.failed error={exc}",
            (),
            sys.exc_info(),
        )
    record.error = str(record.exc_info[1])
    record.diagnostics = {"nested": secret}
    output = formatter.format(record)
    assert secret not in output
    assert "event=database.failed" in output
    assert "IntegrityError" in output
    assert "redacted" in output


def _record(**extra):
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="event=logging_test",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "cid-123"
    record.__dict__.update(extra)
    return record


def test_text_formatter_renders_redacted_extra_context_before_tracebacks():
    formatter = KeyValueFormatter("[CID: %(correlation_id)s] - %(message)s")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = _record(broker="broker:1883", token="supersecrettoken123")
        record.exc_info = sys.exc_info()

    first, *traceback = formatter.format(record).splitlines()

    assert first.startswith("[CID: cid-123] - event=logging_test broker=broker:1883 ")
    assert "supersecrettoken123" not in first
    assert "token=" in first
    assert traceback[-1] == "RuntimeError: boom"
    assert formatter.format(_record()) == "[CID: cid-123] - event=logging_test"


def test_truncated_output_keeps_extra_context():
    formatter = TruncatingFormatter("%(message)s", truncate_length=200)

    assert formatter.format(_record(rows=3)) == "event=logging_test rows=3"


def test_redact_query_params_masks_sensitive_fields():
    redacted = redact_query_params(
        {
            "email": "alice@example.com",
            "token": "supersecrettoken123",
            "page": "1",
        }
    )

    assert redacted["email"] != "alice@example.com"
    assert redacted["token"].startswith("sha256:")
    assert redacted["page"] == "1"


def test_apply_log_format_sets_json_formatter_for_all_handlers():
    config = {
        "handlers": {
            "console": {"formatter": "detailed"},
            "console_truncated": {"formatter": "truncated"},
            "file": {"formatter": "detailed"},
        }
    }

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LOG_FORMAT", "json")
        _apply_log_format(config)

    assert all(
        handler_config["formatter"] == "json"
        for handler_config in config["handlers"].values()
    )


def test_ensure_root_handlers_adds_console_when_missing():
    config = {"root": {"handlers": []}}
    _ensure_root_handlers(config)
    assert config["root"]["handlers"] == ["console"]


def test_expand_env_vars_resolves_nested_fallback_chain(monkeypatch):
    expression = "${TACTIC_LOG_LEVEL:${SERVICE_LOG_LEVEL:${LOG_LEVEL:INFO}}}"

    monkeypatch.delenv("TACTIC_LOG_LEVEL", raising=False)
    monkeypatch.delenv("SERVICE_LOG_LEVEL", raising=False)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    assert _expand_env_vars(expression) == "INFO"

    monkeypatch.setenv("SERVICE_LOG_LEVEL", "WARNING")
    assert _expand_env_vars(expression) == "WARNING"

    monkeypatch.setenv("TACTIC_LOG_LEVEL", "ERROR")
    assert _expand_env_vars(expression) == "ERROR"


def test_load_yaml_config_applies_root_fallback(monkeypatch):
    service_config = (
        Path(__file__).resolve().parents[2]
        / "services/mqtt/proxy/src/off_key_mqtt_proxy/config/logging.yaml"
    )
    assert service_config.exists()

    captured_config = {}

    def _capture_config(config_dict):
        captured_config.clear()
        captured_config.update(config_dict)

    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setattr(logging.config, "dictConfig", _capture_config)

    load_yaml_config(str(service_config))

    assert captured_config["root"]["handlers"] == ["console"]
    assert all(
        handler_config["formatter"] == "json"
        for handler_config in captured_config["handlers"].values()
    )


def test_module_logger_and_service_logger_both_emit_when_configured(monkeypatch):
    service_config = (
        Path(__file__).resolve().parents[2]
        / "services/mqtt/proxy/src/off_key_mqtt_proxy/config/logging.yaml"
    )
    assert service_config.exists()

    root_logger = logging.getLogger()
    service_logger = logging.getLogger("off_key_mqtt_proxy")
    module_logger = logging.getLogger("off_key_mqtt_proxy.router")
    original_root_handlers = list(root_logger.handlers)
    original_root_level = root_logger.level
    original_service_handlers = list(service_logger.handlers)
    original_service_level = service_logger.level
    original_service_propagate = service_logger.propagate
    capture_stream = io.StringIO()

    try:
        load_yaml_config(str(service_config))

        for active_logger in (root_logger, service_logger):
            for handler in active_logger.handlers:
                if hasattr(handler, "stream"):
                    handler.stream = capture_stream

        module_logger.info("event=module_logger_test")
        core_logger.info("event=service_logger_test")

        for active_logger in (root_logger, service_logger):
            for handler in active_logger.handlers:
                handler.flush()

        output = capture_stream.getvalue()
        assert "event=module_logger_test" in output
        assert "event=service_logger_test" in output
    finally:
        for handler in root_logger.handlers:
            with suppress(Exception):
                handler.close()
        for handler in service_logger.handlers:
            if handler not in root_logger.handlers:
                with suppress(Exception):
                    handler.close()

        root_logger.handlers = original_root_handlers
        root_logger.setLevel(original_root_level)
        service_logger.handlers = original_service_handlers
        service_logger.setLevel(original_service_level)
        service_logger.propagate = original_service_propagate


def test_bound_process_context_names_every_record_until_cleared():
    from off_key_core.config.logs import (
        CorrelationFilter,
        bind_log_context,
        clear_log_context,
    )

    formatter = JsonFormatter()
    log_filter = CorrelationFilter()
    try:
        bind_log_context(service_id="svc-1", run_id="run-1", revision_id=None)
        record = _record()
        assert log_filter.filter(record)
        payload = json.loads(formatter.format(record))
        assert payload["extra"] == {"service_id": "svc-1", "run_id": "run-1"}

        # A call site's own value wins over the bound one.
        record = _record(run_id="explicit")
        log_filter.filter(record)
        assert json.loads(formatter.format(record))["extra"]["run_id"] == "explicit"

        bind_log_context(run_id=None)
        record = _record()
        log_filter.filter(record)
        text = KeyValueFormatter("%(message)s").format(record)
        assert text == "event=logging_test service_id=svc-1"
    finally:
        clear_log_context()
    record = _record()
    log_filter.filter(record)
    assert "extra" not in json.loads(formatter.format(record))


@pytest.mark.parametrize(
    "formatter", [JsonFormatter(), KeyValueFormatter("%(message)s")]
)
def test_database_errors_inside_nested_task_groups_are_redacted(formatter):
    secret = "synthetic-private-database-value"
    error = IntegrityError(
        "insert", (secret,), ValueError(secret), hide_parameters=True
    )
    group = ExceptionGroup("workers", [ExceptionGroup("writer", [error])])
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "event=workers.failed",
        (),
        (ExceptionGroup, group, None),
    )
    assert secret not in formatter.format(record)
    assert "IntegrityError" in formatter.format(record)
