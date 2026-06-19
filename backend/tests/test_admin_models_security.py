"""Security regressions for admin model registry endpoints."""

from unittest.mock import MagicMock

import pytest

from off_key_tactic_middleware.api.v1.admin_models import (
    test_model_instantiation as call_test_model_instantiation,
)


def _assert_message_does_not_expose(response: dict, *sensitive_values: str) -> None:
    message = response["message"]
    for sensitive_value in sensitive_values:
        assert sensitive_value not in message


@pytest.mark.asyncio
async def test_model_instantiation_validation_error_hides_exception_detail():
    registry = MagicMock()
    registry.validate_model_instantiation.side_effect = ValueError(
        "secret validation detail /tmp/internal"
    )

    response = await call_test_model_instantiation(
        model_type="isolation_forest",
        test_parameters={"n_estimators": 100},
        model_registry=registry,
    )

    assert response == {
        "success": False,
        "error": "validation_error",
        "message": "Model validation failed. Check model type and parameters.",
    }
    _assert_message_does_not_expose(
        response,
        "secret validation detail",
        "/tmp/internal",
    )
    registry.validate_model_instantiation.assert_called_once_with(
        "isolation_forest",
        {"n_estimators": 100},
    )


@pytest.mark.asyncio
async def test_model_instantiation_import_error_hides_exception_detail():
    registry = MagicMock()
    registry.validate_model_instantiation.side_effect = ImportError(
        "secret.module.path"
    )

    response = await call_test_model_instantiation(
        model_type="isolation_forest",
        test_parameters={"n_estimators": 100},
        model_registry=registry,
    )

    assert response == {
        "success": False,
        "error": "import_error",
        "message": "Model dependencies are not available.",
    }
    _assert_message_does_not_expose(response, "secret.module.path")


@pytest.mark.asyncio
async def test_model_instantiation_internal_error_hides_exception_detail():
    registry = MagicMock()
    registry.validate_model_instantiation.side_effect = RuntimeError(
        "stack trace secret"
    )

    response = await call_test_model_instantiation(
        model_type="isolation_forest",
        test_parameters={"n_estimators": 100},
        model_registry=registry,
    )

    assert response == {
        "success": False,
        "error": "instantiation_error",
        "message": "Model instantiation failed due to an internal error",
    }
    _assert_message_does_not_expose(response, "stack trace secret")


@pytest.mark.asyncio
async def test_model_instantiation_success_reports_runtime_owner():
    registry = MagicMock()
    registry.validate_model_instantiation.return_value = {
        "validated_parameters": {"n_estimators": 100},
        "instantiated": True,
        "runtime_owner": "tactic",
    }

    response = await call_test_model_instantiation(
        model_type="isolation_forest",
        test_parameters={"n_estimators": 100},
        model_registry=registry,
    )

    assert response == {
        "success": True,
        "message": "Model 'isolation_forest' instantiated successfully",
        "validated_parameters": {"n_estimators": 100},
        "instantiated": True,
        "runtime_owner": "tactic",
    }
    registry.validate_model_instantiation.assert_called_once_with(
        "isolation_forest",
        {"n_estimators": 100},
    )
