"""The Timestral step: a pretrained forecaster among the composer's detectors."""

import pytest
from off_key_core.models import ADAPTIVE_MODELS_BY_TYPE, validate_adaptive_model_params
from off_key_core.models.adaptive import (
    CATALOG,
    TIMESTRAL,
    TIMESTRAL_CHECKPOINTS,
    aberrant_model,
    detector_component,
)
from off_key_core.models.pipelines import (
    derive_monitoring_config,
    pipeline_components,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_forecast.providers.timestral import CHECKPOINTS

from tests.support.pipelines import template

IFOREST = "detector:pyod_iforest"
MAD = "detector:aberrant_moving_average_absolute_deviation"
PARAMS = {IFOREST: {"n_estimators": 10}, MAD: {"window_size": 10}}


def _design(
    *detectors, slots=1, params=None, policy="policy.quantile", scaler=None
) -> PipelineDefinition:
    """A schema 2 design: each detector reads the input, all feed one fixed split.

    ``scaler`` puts a learned step in front of the first detector.
    """
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    edges = []
    for index, component in enumerate(detectors, start=1):
        identifier = f"detector_{index}"
        nodes.append(
            {
                "id": identifier,
                "kind": "detector",
                "component": component,
                "params": PARAMS.get(component, params or {}),
            }
        )
        reads = "input"
        if scaler is not None and index == 1:
            nodes.append({"id": "scale", "kind": "transform", "component": scaler})
            edges.append({"source": "input", "target": "scale"})
            reads = "scale"
        edges.append({"source": reads, "target": identifier})
        edges.append({"source": identifier, "target": "calibrate", "order": index - 1})
    nodes += [
        {
            "id": "calibrate",
            "kind": "calibration",
            "component": "calibrate.fixed_split",
        },
        {"id": "policy", "kind": "policy", "component": policy},
        {"id": "output", "kind": "output", "component": "output.evidence"},
    ]
    edges += [
        {"source": "calibrate", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(
        {
            "schema_version": 2,
            "input_slots": [
                {"id": f"slot_{index}", "label": f"Slot {index}"}
                for index in range(slots)
            ],
            "nodes": nodes,
            "edges": edges,
            "settings": {"training_window_size": 30, "calibration_window_size": 20},
        }
    )


def _issues(definition):
    return [
        (item.code, item.node_id, item.message)
        for item in validate_pipeline(definition).issues
    ]


def test_timestral_is_a_pretrained_forecaster_step_of_its_own():
    component = {item.id: item for item in pipeline_components()}[TIMESTRAL]

    assert detector_component(TIMESTRAL) == TIMESTRAL
    assert (component.kind, component.learning) == ("detector", "pretrained")
    assert (component.strategies, component.output_type) == (
        ["adaptive_stream"],
        "scores",
    )
    assert "forecast" in component.description
    assert {field.name for field in component.fields} == {
        "checkpoint",
        "context_length",
        "minimum_context",
        "lead",
        "score",
        "min_scale",
    }
    # The weights are the forecast service's, so Aberrant's catalog has no entry.
    assert TIMESTRAL not in CATALOG["models"]
    assert ADAPTIVE_MODELS_BY_TYPE[TIMESTRAL]["bound_parameters"] == ["target"]


def test_timestral_offers_the_checkpoints_of_the_forecast_service():
    assert tuple(CHECKPOINTS) == TIMESTRAL_CHECKPOINTS


def test_timestral_settings_nest_into_a_residual_detector_over_the_service():
    params = validate_adaptive_model_params(TIMESTRAL, {"lead": 3})
    model = aberrant_model(ADAPTIVE_MODELS_BY_TYPE[TIMESTRAL], params)

    assert params["checkpoint"] == TIMESTRAL_CHECKPOINTS[0]
    assert model["id"] == "residual_detector"
    assert (model["params"]["lead"], model["params"]["score"]) == (3, "scaled")
    assert model["params"]["model"] == {
        "id": TIMESTRAL,
        "params": {
            "checkpoint": TIMESTRAL_CHECKPOINTS[0],
            "context_length": 512,
            "minimum_context": 32,
            "min_scale": 1e-06,
            "horizon": 3,
        },
    }


@pytest.mark.parametrize(
    "params",
    [
        {"checkpoint": "mistralai/Timestral-1B"},
        {"context_length": 8},
        {"context_length": 64, "minimum_context": 65},
        {"lead": 0},
        {"horizon": 4},
        {"target": "x"},
        {"score": "cqr"},
        {"season_length": 24},
    ],
)
def test_timestral_rejects_settings_it_does_not_have(params):
    with pytest.raises(ValueError):
        validate_adaptive_model_params(TIMESTRAL, params)


def test_timestral_in_a_lane_design_runs_as_an_adaptive_stream():
    data = template("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    detector["component"] = TIMESTRAL
    detector["params"] = {"lead": 2}
    definition = PipelineDefinition.model_validate(data)

    assert validate_pipeline(definition).valid
    monitoring = derive_monitoring_config(definition)
    assert (monitoring.strategy, monitoring.model_type) == (
        "adaptive_stream",
        TIMESTRAL,
    )
    assert monitoring.model_params["lead"] == 2

    data["strategy"] = "static_baseline"
    assert not validate_pipeline(PipelineDefinition.model_validate(data)).valid


def test_timestral_reads_one_feature_and_sits_beside_other_detectors():
    assert _issues(_design(TIMESTRAL, params={"lead": 2})) == []
    assert _issues(_design(TIMESTRAL, MAD)) == []
    assert _issues(_design(TIMESTRAL, IFOREST)) == []

    [(code, node, _)] = _issues(_design(TIMESTRAL, slots=2))
    assert (code, node) == ("model_features", "detector_1")
    [(code, node, _)] = _issues(_design(TIMESTRAL, params={"lead": 0}))
    assert (code, node) == ("parameters", "detector_1")


@pytest.mark.parametrize(
    "scaler", ["adaptive.standard_scaler", "static.standard_scaler"]
)
def test_timestral_reads_no_step_that_learns(scaler):
    [(code, node, message)] = _issues(_design(TIMESTRAL, scaler=scaler))

    assert (code, node) == ("learning", "scale")
    assert message.endswith(
        "can't feed Timestral forecaster: the detector is pretrained and reads "
        "only steps that do not learn."
    )


def test_the_conformal_alarm_policy_does_not_run_on_timestral():
    [(code, node, message)] = _issues(_design(TIMESTRAL, policy="policy.martingale"))

    assert (code, node) == ("calibration", "policy")
    assert "pretrained forecaster" in message
