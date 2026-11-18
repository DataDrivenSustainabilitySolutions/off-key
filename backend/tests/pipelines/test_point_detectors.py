"""A detector that scores observations alone is told when nothing gives it time."""

import pytest
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition

from tests.support.pipelines import template

TIMELESS = "point_detector_without_time"


def design(strategy, detector=None, step=None):
    """A bundled design with another detector, and a step right after the input."""
    data = template(strategy).model_dump(mode="json")
    model = next(node for node in data["nodes"] if node["kind"] == "detector")
    if detector:
        model.update(component=detector, params={})
    if step:
        component, params = step
        data["nodes"].append(
            {
                "id": "time",
                "kind": "transform",
                "component": component,
                "params": params,
            }
        )
        for edge in data["edges"]:
            if edge["source"] == "input":
                edge["source"] = "time"
        data["edges"].append({"source": "input", "target": "time"})
    return PipelineDefinition.model_validate(data)


def timeless(definition):
    return [
        item.node_id
        for item in validate_pipeline(definition).issues
        if item.code == TIMELESS
    ]


@pytest.mark.parametrize(
    "detector",
    [
        "detector:aberrant_half_space_trees",
        "detector:aberrant_online_ecod",
        "detector:aberrant_streaming_loda",
    ],
)
def test_a_point_detector_on_raw_values_is_told_to_take_time_in(detector):
    found = validate_pipeline(design("adaptive_stream", detector)).issues
    [issue] = [item for item in found if item.code == TIMELESS]
    assert issue.severity == "warning"
    assert "Lags or Change" in issue.message and "DAMP" in issue.message


def test_a_static_detector_is_a_point_detector_too():
    assert timeless(design("static_baseline"))


@pytest.mark.parametrize(
    "step",
    [
        ("prepare.lags", {"lags": [1, 2], "unit": "observations"}),
        ("prepare.change", {}),
        ("prepare.time", {}),
    ],
)
def test_a_step_that_carries_time_quiets_it(step):
    assert (
        timeless(design("adaptive_stream", "detector:aberrant_half_space_trees", step))
        == []
    )


@pytest.mark.parametrize(
    "detector",
    [
        "detector:aberrant_moving_median",
        "detector:aberrant_rolling_matrix_profile",
        "detector:aberrant_x_lag_damp",
    ],
)
def test_a_detector_that_reads_the_past_needs_no_step(detector):
    assert timeless(design("adaptive_stream", detector)) == []
