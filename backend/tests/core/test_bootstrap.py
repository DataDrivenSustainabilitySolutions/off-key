"""Service entry points share one start-up order."""

from pathlib import Path

import pytest
from off_key_core.config import bootstrap


@pytest.fixture
def calls(monkeypatch):
    calls = []
    monkeypatch.setattr(bootstrap, "load_env", lambda: calls.append("env"))
    monkeypatch.setattr(
        bootstrap, "load_yaml_config", lambda path: calls.append(("yaml", path))
    )
    monkeypatch.setattr(
        bootstrap,
        "log_startup_logging_configuration",
        lambda name: calls.append(("startup", name)),
    )
    monkeypatch.setattr(
        bootstrap,
        "validate_settings",
        lambda specs, context: calls.append(("validate", list(specs), context)),
    )
    return calls


def test_environment_then_hook_then_logging_then_validation(calls):
    spec = ("example", lambda: None)

    result = bootstrap.start_service(
        "example",
        Path("/service/logging.yaml"),
        [spec],
        "Example configuration",
        after_env=lambda: calls.append("hook") or "loaded.env",
    )

    assert result == "loaded.env"
    assert calls == [
        "env",
        "hook",
        ("yaml", "/service/logging.yaml"),
        ("startup", "example"),
        ("validate", [spec], "Example configuration"),
    ]


def test_without_service_yaml_only_core_logging_loads(calls):
    assert bootstrap.start_service("example", None, [], "Example") is None
    assert ("yaml", None) in calls
    assert "hook" not in calls
