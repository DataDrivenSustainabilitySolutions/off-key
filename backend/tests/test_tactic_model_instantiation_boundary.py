import pytest
from fastapi import HTTPException
from off_key_tactic_middleware.api.v1.admin_models import (
    test_model_instantiation as admin_test_model_instantiation,
)
from off_key_tactic_middleware.api.v1.models import (
    ModelInstanceRequest,
    create_model_instance,
)


class FakeRegistry:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def validate_model_instantiation(self, model_type, params):
        self.calls.append((model_type, params))
        return self.result


class FailingRegistry:
    def __init__(self, error):
        self.error = error

    def validate_model_instantiation(self, _model_type, _params):
        raise self.error


@pytest.mark.asyncio
async def test_create_instance_defers_static_pyod_to_radar_runtime():
    registry = FakeRegistry(
        {
            "validated_parameters": {"n_estimators": 100},
            "instantiated": False,
            "runtime_owner": "radar",
        }
    )

    response = await create_model_instance(
        ModelInstanceRequest(model_type="pyod_iforest", parameters={}),
        model_registry=registry,
    )

    assert response["success"] is True
    assert response["instantiated"] is False
    assert response["runtime_owner"] == "radar"
    assert response["validated_parameters"] == {"n_estimators": 100}
    assert registry.calls == [("pyod_iforest", {})]


@pytest.mark.asyncio
async def test_create_instance_hides_validation_exception_detail():
    with pytest.raises(HTTPException) as exc_info:
        await create_model_instance(
            ModelInstanceRequest(
                model_type="pyod_iforest",
                parameters={"secret": "internal-path"},
            ),
            model_registry=FailingRegistry(
                ValueError("secret validation detail /tmp/internal")
            ),
        )

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail
        == "Model validation failed. Check model type and parameters."
    )
    assert "secret validation detail" not in exc_info.value.detail
    assert "/tmp/internal" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_instance_hides_import_exception_detail():
    with pytest.raises(HTTPException) as exc_info:
        await create_model_instance(
            ModelInstanceRequest(model_type="pyod_iforest", parameters={}),
            model_registry=FailingRegistry(ImportError("secret.module.path")),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Model dependencies are not available."
    assert "secret.module.path" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_admin_model_test_reports_tactic_owned_instantiation():
    registry = FakeRegistry(
        {
            "validated_parameters": {"k": 5},
            "instantiated": True,
            "runtime_owner": "tactic",
        }
    )

    response = await admin_test_model_instantiation(
        "knn",
        test_parameters={"k": 5},
        model_registry=registry,
    )

    assert response["success"] is True
    assert response["instantiated"] is True
    assert response["runtime_owner"] == "tactic"
    assert registry.calls == [("knn", {"k": 5})]
