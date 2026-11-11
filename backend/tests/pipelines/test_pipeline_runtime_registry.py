"""Every component core's catalog offers has a RADAR runtime implementation."""

import pytest
from off_key_core.models.pipeline_catalog import pipeline_components
from off_key_core.models.pipeline_combine import row_step
from off_key_core.models.pipeline_features import PROJECTIONS
from off_key_core.models.pipeline_prepare import (
    LANE_COMPONENTS,
    PREPARE_COMPONENTS,
    kernel,
)
from off_key_mqtt_radar.pipelines.components import (
    BATCH_BUILDERS,
    BATCH_PASSTHROUGH,
    ONLINE_BUILDERS,
    batch_component,
    online_component,
)
from off_key_mqtt_radar.pipelines.resources import STATE_ESTIMATORS

FEATURE_COMPONENTS = [
    item for item in pipeline_components() if item.kind in {"transform", "merge"}
]
# Steps over the whole row need settings without a default.
ROW_SETTINGS = {
    "prepare.aggregate": {},
    "prepare.formula": {"expression": "a * b"},
    "prepare.gate": {"condition": "a > 1"},
    "prepare.constant": {},
    "prepare.condition": {"condition": "a > 1"},
    "prepare.set": {"name": "a", "expression": "a + b"},
    "prepare.calculate": {"formulas": "c = a + b"},
}
# Likewise for the steps that read the row for each feature.
LANE_SETTINGS = {
    "prepare.hold": {"update_when": "a > 1"},
    "prepare.relation": {"against": "b"},
}


@pytest.mark.parametrize("component", FEATURE_COMPONENTS, ids=lambda item: item.id)
def test_the_runtime_can_build_every_feature_component_the_catalog_offers(component):
    if component.id in PREPARE_COMPONENTS:
        # Prepare steps learn nothing and run in the same stage for every detector.
        assert component.learning == "none"
        if component.id in LANE_COMPONENTS:
            settings = LANE_SETTINGS.get(component.id, {})
            assert kernel(component.id, settings).initial() is not None
        else:
            settings = ROW_SETTINGS[component.id]
            assert row_step(component.id, settings, ["a", "b"]) is not None
        return
    # A step that learns nothing runs beside either kind of detector.
    if component.learning in ("none", "batch"):
        assert component.id in BATCH_PASSTHROUGH | BATCH_BUILDERS.keys()
    if component.learning in ("none", "online"):
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
