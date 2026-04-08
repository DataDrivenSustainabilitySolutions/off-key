import io
import json
import logging
import logging.config

from pathlib import Path

import pytest

from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import (
    JsonFormatter,
    _expand_env_vars,
    _apply_log_format,
    _ensure_root_handlers,
    load_yaml_config,
    logger as core_logger,
    redact_query_params,
)


@pytest.fixture(autouse=True)
def clear_logging_settings_cache():
    get_logging_settings.cache_clear()
    yield
    get_logging_settings.cache_clear()


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
        Path(__file__).resolve().parents[1]
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


def test_module_logger_and_service_logger_both_emit_when_configured(
    monkeypatch, tmp_path
):
    service_config = (
        Path(__file__).resolve().parents[1]
        / "services/mqtt/proxy/src/off_key_mqtt_proxy/config/logging.yaml"
    )
    assert service_config.exists()

    log_file = str(tmp_path / "logging-test.log")
    monkeypatch.setenv("LOG_FILE", log_file)
    monkeypatch.setenv("MQTT_PROXY_LOG_FILE", log_file)
    monkeypatch.setenv("SERVICE_LOG_FILE", log_file)
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
            try:
                handler.close()
            except Exception:
                pass
        for handler in service_logger.handlers:
            if handler not in root_logger.handlers:
                try:
                    handler.close()
                except Exception:
                    pass

        root_logger.handlers = original_root_handlers
        root_logger.setLevel(original_root_level)
        service_logger.handlers = original_service_handlers
        service_logger.setLevel(original_service_level)
        service_logger.propagate = original_service_propagate
