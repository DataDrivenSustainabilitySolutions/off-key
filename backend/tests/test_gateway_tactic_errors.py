import pytest
from fastapi import HTTPException, status
from off_key_api_gateway.api.errors import (
    raise_tactic_http_error,
    tactic_error_detail,
)
from off_key_api_gateway.facades.tactic import TacticError


def test_tactic_error_detail_prefers_downstream_api_detail():
    error = TacticError(
        "downstream request failed",
        status=status.HTTP_409_CONFLICT,
        body={"detail": "sensor is already claimed"},
    )

    assert tactic_error_detail(error) == "sensor is already claimed"


def test_raise_tactic_http_error_preserves_status_and_cause():
    error = TacticError(
        "downstream request failed",
        status=status.HTTP_404_NOT_FOUND,
        body={"detail": "service not found"},
    )

    with pytest.raises(HTTPException) as exc_info:
        raise_tactic_http_error(error)

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "service not found"
    assert exc_info.value.__cause__ is error


def test_raise_tactic_http_error_defaults_to_bad_gateway():
    error = TacticError("connection failed")

    with pytest.raises(HTTPException) as exc_info:
        raise_tactic_http_error(error)

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert exc_info.value.detail == "connection failed"
