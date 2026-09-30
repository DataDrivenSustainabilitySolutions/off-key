import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.db.models import ModelRegistry
from off_key_core.models import STATIC_MODEL_FAMILY
from off_key_core.models.static import STATIC_MODELS, validate_static_model_params
from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_tactic_middleware.api.v1.admin_models import UpdateModelRequest, router
from off_key_tactic_middleware.domain import ValidationError as DomainValidationError
from off_key_tactic_middleware.models.registry import ModelRegistryService
from off_key_tactic_middleware.repositories.admin_models import (
    ModelRegistryAdminRepository,
)
from off_key_tactic_middleware.services.admin_models import ModelRegistryAdminService
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


@pytest.mark.parametrize("model_type", STATIC_MODELS)
def test_every_advertised_static_model_instantiates_in_radar(model_type):
    definition = STATIC_MODELS[model_type]
    detector = object.__new__(StaticConformalDetectionService)
    params = validate_static_model_params(model_type, {})
    instance = detector._instantiate_pyod_detector(model_type, params)
    assert (
        f"{type(instance).__module__}.{type(instance).__name__}"
        == definition.import_path
    )


def test_custom_models_are_rejected_before_start_and_cannot_be_registered():
    with pytest.raises(ValidationError, match="Unsupported static PyOD model"):
        StaticBaselineConfig(model_type="custom_static_detector")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/admin/models/", json={"model_type": "custom_static_detector"}
        )
    assert response.status_code == 405


@pytest.mark.parametrize(
    "field", ["import_paths", "parameter_schema", "family", "requires_special_handling"]
)
def test_admin_cannot_redefine_executable_contract(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        UpdateModelRequest(**{field: "override"})


def test_registry_preserves_admin_overrides_and_retires_unsupported_models(monkeypatch):
    engine = create_engine("sqlite://")
    ModelRegistry.__table__.create(engine)
    registry = ModelRegistryService()
    try:
        with Session(engine) as session:
            registry._populate_default_models(session)
            session.commit()
            model = session.scalar(
                select(ModelRegistry).where(ModelRegistry.model_type == "pyod_knn")
            )
            model.name = "Approved KNN"
            model.default_parameters = {"n_neighbors": 9}
            model.is_active = False
            session.add(
                ModelRegistry(
                    model_type="custom_static_detector",
                    category="model",
                    family=STATIC_MODEL_FAMILY,
                    name="Unsupported",
                    import_paths=["example.Detector"],
                    parameter_schema={},
                )
            )
            session.commit()
            registry._populate_default_models(session)
            session.commit()
            assert model.name == "Approved KNN" and not model.is_active
            assert model.default_parameters == {"n_neighbors": 9}

            admin = ModelRegistryAdminService(ModelRegistryAdminRepository(session))
            with pytest.raises(DomainValidationError):
                admin.update_model(
                    model_type="pyod_knn",
                    update_data={"default_parameters": {"n_neighbors": -1}},
                )
            with pytest.raises(DomainValidationError, match="not shipped"):
                admin.update_model(
                    model_type="custom_static_detector", update_data={"is_active": True}
                )

        monkeypatch.setattr(
            "off_key_tactic_middleware.models.registry.get_engine", lambda: engine
        )
        registry._initialized = True
        available = {model["model_type"] for model in registry.get_available_models()}
        assert "pyod_knn" not in available and "custom_static_detector" not in available
    finally:
        engine.dispose()
