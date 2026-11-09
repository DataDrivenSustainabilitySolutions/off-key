"""Every component core's catalog offers has a RADAR runtime implementation."""

import pytest
from aberration_core.models.pipeline_catalog import pipeline_components
from aberration_core.models.pipeline_combine import row_step
from aberration_core.models.pipeline_features import PROJECTIONS
from aberration_core.models.pipeline_prepare import (
    LANE_COMPONENTS,
    PREPARE_COMPONENTS,
    kernel,
)
from aberration_mqtt_radar.pipelines.components import (
    BATCH_BUILDERS,
    BATCH_PASSTHROUGH,
    ONLINE_BUILDERS,
    batch_component,
    online_component,
)
from aberration_mqtt_radar.pipelines.resources import STATE_ESTIMATORS

FEATURE_COMPONENTS = [
    item for item in pipeline_components() if item.kind in {"transform", "merge"}
]
# Steps over the whole row need settings without a default.
ROW_SETTINGS = {
    "prepare.aggregate": {},
    "prepare.formula": {"expression": "a * b"},
    "prepare.gate": {"condition": "a > 1"},
}


@pytest.mark.parametrize("component", FEATURE_COMPONENTS, ids=lambda item: item.id)
def test_each_strategy_can_build_the_feature_components_it_offers(component):
    if component.id in PREPARE_COMPONENTS:
        # Both strategies run Prepare steps in the same Prepare stage.
        assert set(component.strategies) == {"static_baseline", "adaptive_stream"}
        if component.id in LANE_COMPONENTS:
            assert kernel(component.id, {}).initial() is not None
        else:
            settings = ROW_SETTINGS[component.id]
            assert row_step(component.id, settings, ["a", "b"]) is not None
        return
    if "static_baseline" in component.strategies:
        assert component.id in BATCH_PASSTHROUGH | BATCH_BUILDERS.keys()
    if "adaptive_stream" in component.strategies:
        assert component.id == "features.merge" or component.id in ONLINE_BUILDERS


def test_runtime_registries_hold_no_component_the_catalog_lacks():
    offered = {item.id for item in FEATURE_COMPONENTS}
    assert BATCH_PASSTHROUGH | BATCH_BUILDERS.keys() <= offered
    assert ONLINE_BUILDERS.keys() <= offered


def test_every_projection_and_rolling_window_has_a_state_estimate():
    assert set(STATE_ESTIMATORS) == PROJECTIONS | {"adaptive.robust_scaler"}


def test_unknown_components_keep_their_strategy_specific_errors():
    node = type("Node", (), {"id": "n", "component": "static.mystery", "params": {}})
    with pytest.raises(ValueError, match="Unsupported static component"):
        batch_component(node)
    node.component = "adaptive.mystery"
    with pytest.raises(ValueError, match="Unsupported adaptive component"):
        online_component(None, node, [])
