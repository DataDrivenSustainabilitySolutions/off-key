import pytest
from off_key_core.models import STATIC_MODEL_FAMILY
from off_key_tactic_middleware.api.v1.admin_models import CreateModelRequest
from off_key_tactic_middleware.config.config import RadarDefaultsConfig
from pydantic import ValidationError


def _request(**overrides) -> CreateModelRequest:
    payload = {
        "model_type": "custom_static_detector",
        "family": STATIC_MODEL_FAMILY,
        "name": "Custom static detector",
        "import_paths": ["example.detectors.CustomDetector"],
        "parameter_schema": {"type": "object"},
    }
    return CreateModelRequest(**{**payload, **overrides})


def test_admin_accepts_new_static_family_model_without_code_allowlist():
    assert _request().model_type == "custom_static_detector"


def test_admin_rejects_non_static_family():
    with pytest.raises(ValidationError, match=STATIC_MODEL_FAMILY):
        _request(family="dynamic")


def test_radar_defaults_do_not_classify_models_by_name_prefix():
    assert RadarDefaultsConfig(model_type="custom_static_detector").model_type == (
        "custom_static_detector"
    )
