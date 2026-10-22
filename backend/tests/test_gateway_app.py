"""The production gateway composition: middleware order and error handlers."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from off_key_api_gateway.api.middleware import (
    LoggingMiddleware,
    SecurityLoggingMiddleware,
)
from off_key_api_gateway.app import build_app
from off_key_core.config.app import AppSettings
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware


def test_middleware_runs_cors_first_and_request_logging_last():
    app = build_app(AppSettings(APP_NAME="off-key-test"))

    assert [middleware.cls for middleware in app.user_middleware] == [
        CORSMiddleware,
        GZipMiddleware,
        SlowAPIMiddleware,
        SecurityLoggingMiddleware,
        LoggingMiddleware,
    ]


def test_only_rate_limits_get_a_custom_exception_handler():
    app = build_app(AppSettings(APP_NAME="off-key-test"))

    # TacticError is translated per router, never by an app-level handler.
    assert set(app.exception_handlers) - set(FastAPI().exception_handlers) == {429}
