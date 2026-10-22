"""Every component core's catalog offers has a RADAR runtime implementation."""

import pytest
from off_key_core.models.pipeline_catalog import pipeline_components
from off_key_core.models.pipeline_features import PROJECTIONS
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


@pytest.mark.parametrize("component", FEATURE_COMPONENTS, ids=lambda item: item.id)
def test_each_strategy_can_build_the_feature_components_it_offers(component):
    if "static_baseline" in component.strategies:
        assert component.id in BATCH_PASSTHROUGH | BATCH_BUILDERS.keys()
    if "adaptive_stream" in component.strategies:
        assert component.id == "features.merge" or component.id in ONLINE_BUILDERS


def test_runtime_registries_hold_no_component_the_catalog_lacks():
    offered = {item.id for item in FEATURE_COMPONENTS}
    assert BATCH_PASSTHROUGH | BATCH_BUILDERS.keys() <= offered
    assert ONLINE_BUILDERS.keys() <= offered


def test_every_projection_has_a_state_estimate():
    assert set(STATE_ESTIMATORS) == PROJECTIONS


def test_unknown_components_keep_their_strategy_specific_errors():
    node = type("Node", (), {"id": "n", "component": "static.mystery", "params": {}})
    with pytest.raises(ValueError, match="Unsupported static component"):
        batch_component(node)
    node.component = "adaptive.mystery"
    with pytest.raises(ValueError, match="Unsupported adaptive component"):
        online_component(None, node, [])
