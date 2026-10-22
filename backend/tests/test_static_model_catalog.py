import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_core.models import (
    ADAPTIVE_MODELS_BY_TYPE,
    ADAPTIVE_MONITORING_STRATEGY,
    STATIC_MODEL_FAMILY,
    STATIC_MONITORING_STRATEGY,
)
from off_key_core.models.static import STATIC_MODELS, validate_static_model_params
from off_key_core.schemas.radar import StaticBaselineConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_tactic_middleware.api.v1.models import router
from off_key_tactic_middleware.models.catalog import validate_model_params
from pydantic import ValidationError


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


def test_custom_models_are_rejected_before_start():
    with pytest.raises(ValidationError, match="Unsupported static PyOD model"):
        StaticBaselineConfig(model_type="custom_static_detector")
    with pytest.raises(ValueError, match="Unknown model type"):
        validate_model_params("custom_static_detector", {}, family=STATIC_MODEL_FAMILY)


def test_catalogue_lists_every_shipped_model_with_its_strategy():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        models = client.get("/models/").json()
        adaptive = client.get(
            "/models/", params={"strategy": ADAPTIVE_MONITORING_STRATEGY}
        ).json()

    assert [model["model_type"] for model in models] == [
        *STATIC_MODELS,
        *ADAPTIVE_MODELS_BY_TYPE,
    ]
    assert {model["model_type"] for model in adaptive} == set(ADAPTIVE_MODELS_BY_TYPE)
    knn = next(model for model in models if model["model_type"] == "pyod_knn")
    assert knn["strategy"] == STATIC_MONITORING_STRATEGY
    assert knn["family"] == STATIC_MODEL_FAMILY
    assert knn["default_parameters"] == validate_static_model_params("pyod_knn", {})


def test_validation_merges_catalogue_defaults():
    params = validate_model_params(
        "pyod_knn", {"n_neighbors": 9}, family=STATIC_MODEL_FAMILY
    )
    assert params == validate_static_model_params("pyod_knn", {"n_neighbors": 9})
    with pytest.raises(ValueError):
        validate_model_params(
            "pyod_knn", {"n_neighbors": -1}, family=STATIC_MODEL_FAMILY
        )
