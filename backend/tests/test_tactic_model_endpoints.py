"""TACTIC model endpoints report runtime ownership and hide internal error detail."""

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from off_key_tactic_middleware.api.v1.admin_models import (
    test_model_instantiation as admin_test_model_instantiation,
)
from off_key_tactic_middleware.api.v1.models import (
    ModelInstanceRequest,
    create_model_instance,
)

DEFERRED = "parameters validated; instantiation is deferred to the RADAR runtime"
VALIDATION_ERROR = ValueError("secret validation detail /tmp/internal")
IMPORT_ERROR = ImportError("secret.module.path")
RUNTIME_ERROR = RuntimeError("stack trace secret")
VALIDATION_FAILED = "Model validation failed. Check model type and parameters."
DEPENDENCIES_MISSING = "Model dependencies are not available."


def _registry(result=None, error=None):
    registry = MagicMock()
    registry.validate_model_instantiation.return_value = result
    registry.validate_model_instantiation.side_effect = error
    return registry


def _validated(instantiated, runtime_owner):
    return {
        "validated_parameters": {"k": 5},
        "instantiated": instantiated,
        "runtime_owner": runtime_owner,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_type", "instantiated", "runtime_owner", "message"),
    [
        ("knn", True, "tactic", "Model 'knn' instantiated successfully"),
        ("pyod_iforest", False, "radar", f"Model 'pyod_iforest' {DEFERRED}"),
    ],
)
async def test_admin_model_test_reports_runtime_owner(
    model_type, instantiated, runtime_owner, message
):
    registry = _registry(_validated(instantiated, runtime_owner))

    response = await admin_test_model_instantiation(
        model_type, test_parameters={"k": 5}, model_registry=registry
    )

    assert response == {
        "success": True,
        "message": message,
        **_validated(instantiated, runtime_owner),
    }
    registry.validate_model_instantiation.assert_called_once_with(model_type, {"k": 5})


@pytest.mark.asyncio
async def test_admin_model_test_validates_default_parameters():
    registry = _registry(_validated(True, "tactic"))

    await admin_test_model_instantiation("knn", model_registry=registry)

    registry.validate_model_instantiation.assert_called_once_with("knn", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (VALIDATION_ERROR, "validation_error", VALIDATION_FAILED),
        (IMPORT_ERROR, "import_error", DEPENDENCIES_MISSING),
        (
            RUNTIME_ERROR,
            "instantiation_error",
            "Model instantiation failed due to an internal error",
        ),
    ],
)
async def test_admin_model_test_hides_exception_detail(error, code, message):
    registry = _registry(error=error)

    response = await admin_test_model_instantiation(
        "isolation_forest",
        test_parameters={"n_estimators": 100},
        model_registry=registry,
    )

    assert response == {"success": False, "error": code, "message": message}
    registry.validate_model_instantiation.assert_called_once_with(
        "isolation_forest", {"n_estimators": 100}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_type", "instantiated", "runtime_owner", "message"),
    [
        ("knn", True, "tactic", "Model 'knn' created successfully"),
        ("pyod_iforest", False, "radar", f"Model 'pyod_iforest' {DEFERRED}"),
    ],
)
async def test_create_instance_reports_runtime_owner(
    model_type, instantiated, runtime_owner, message
):
    registry = _registry(_validated(instantiated, runtime_owner))

    response = await create_model_instance(
        ModelInstanceRequest(model_type=model_type, parameters={}),
        model_registry=registry,
    )

    assert response == {
        "success": True,
        "message": message,
        "model_type": model_type,
        **_validated(instantiated, runtime_owner),
    }
    registry.validate_model_instantiation.assert_called_once_with(model_type, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (VALIDATION_ERROR, 400, VALIDATION_FAILED),
        (IMPORT_ERROR, 422, DEPENDENCIES_MISSING),
        (RUNTIME_ERROR, 500, "Model creation failed"),
    ],
)
async def test_create_instance_hides_exception_detail(error, status_code, detail):
    with pytest.raises(HTTPException) as exc_info:
        await create_model_instance(
            ModelInstanceRequest(
                model_type="pyod_iforest", parameters={"secret": "internal-path"}
            ),
            model_registry=_registry(error=error),
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail == detail
    assert exc_info.value.__cause__ is error
