"""Calibration steps that keep adapting, and the exceedance rule on them.

The methods come from aberrant.calibration through a generated catalog. A
policy fits its calibration step: the fixed split gives exact p-values and a
frozen threshold, an adapting method gives a boundary for the exceedance rule.
"""

import math

import pytest
from aberrant import __version__
from aberrant.calibration import CALIBRATORS as RUNTIME
from aberrant.calibration import ScoreCalibrator
from off_key_core.models.pipeline_calibration import (
    CALIBRATION_CATALOG,
    CALIBRATION_MODELS,
    CALIBRATORS,
    calibrator_id,
    minimum_window,
)
from off_key_core.models.pipeline_catalog import pipeline_catalog
from off_key_core.models.pipelines import (
    derive_monitoring_config,
    pipeline_components,
    validate_pipeline,
)
from off_key_core.schemas.pipeline_versions import derived_strategy
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from off_key_mqtt_radar.calibration_catalog import generate_calibration_catalog

from tests.support.boundary_pipeline import boundary_definition
from tests.support.fused_pipeline import fused_definition

SHAPES = [("forest",), ("mad",), ("forest", "mad")]


def issues(definition):
    return [
        (item.code, item.node_id, item.severity)
        for item in validate_pipeline(definition).issues
    ]


def test_the_generated_catalog_matches_the_pinned_runtime():
    assert CALIBRATION_CATALOG["aberrant_version"] == __version__
    assert generate_calibration_catalog() == CALIBRATION_CATALOG
    assert list(CALIBRATORS) == list(RUNTIME)


def test_every_method_is_a_calibration_step_with_its_own_settings():
    components = {item.id: item for item in pipeline_components()}

    for method, spec in CALIBRATORS.items():
        component = components[f"calibrate.{method}"]
        assert (component.kind, component.label) == ("calibration", spec["name"])
        assert (component.input_type, component.output_type) == ("scores", "p_values")
        assert calibrator_id(component.id) == method
        fields = {item.name: item for item in component.fields}
        assert list(fields) == [
            "alpha",
            *(parameter["key"] for parameter in spec["parameters"]),
            "fusion",
        ]
        assert fields["alpha"].default == 0.01
        defaults = CALIBRATION_MODELS[component.id]().model_dump()
        # The runtime takes what the control plane offers.
        ScoreCalibrator(
            method,
            alpha=defaults.pop("alpha"),
            window=100,
            **{key: value for key, value in defaults.items() if key != "fusion"},
        )
    assert calibrator_id("calibrate.fixed_split") is None
    assert calibrator_id("calibrate.unknown") is None
    rule = components["policy.exceedance"]
    assert (rule.kind, rule.input_type) == ("policy", "p_values")
    assert [item.name for item in rule.fields] == ["consecutive"]


def test_the_editor_is_offered_every_calibration_step_and_what_it_holds():
    catalog = pipeline_catalog()
    offered = {item.id: item for item in catalog.components}

    assert [item.id for item in catalog.components] == [
        item.id for item in pipeline_components()
    ]
    assert "policy.exceedance" in offered
    fixed = offered["calibrate.fixed_split"]
    assert (fixed.family, fixed.coverage, fixed.reference) == (
        "conformal",
        "exchangeable",
        None,
    )
    for method, spec in CALIBRATORS.items():
        component = offered[f"calibrate.{method}"]
        assert (component.family, component.coverage, component.reference) == (
            spec["family"],
            spec["coverage"],
            spec["reference"],
        )
    assert all(
        item.family is None for item in offered.values() if item.kind != "calibration"
    )


@pytest.mark.parametrize("detectors", SHAPES)
def test_the_exceedance_rule_runs_over_any_detectors(detectors):
    result = validate_pipeline(boundary_definition(detectors))

    assert result.valid, result.issues
    assert result.issues == []


@pytest.mark.parametrize(
    ("policy", "reason"),
    [
        ("policy.martingale", "exact"),
        ("policy.quantile", "fixed split"),
    ],
)
@pytest.mark.parametrize("detectors", [("forest",), ("mad",)])
def test_a_fixed_split_policy_refuses_an_adapting_step(policy, reason, detectors):
    result = validate_pipeline(boundary_definition(detectors, policy=policy))
    found = [item for item in result.issues if item.code == "calibration"]

    assert not result.valid
    assert [item.node_id for item in found] == ["policy"]
    assert reason in found[0].message
    assert "With ACI, use the exceedance rule." in found[0].message


def test_the_exceedance_rule_refuses_the_fixed_split():
    result = validate_pipeline(
        boundary_definition(("mad",), calibration="calibrate.fixed_split", params={})
    )
    found = [item for item in result.issues if item.code == "calibration"]

    assert not result.valid
    assert [item.node_id for item in found] == ["policy"]
    assert "use the calibrated score threshold" in found[0].message


@pytest.mark.parametrize(
    ("params", "path"),
    [
        ({"alpha": 0.0}, ["alpha"]),
        ({"alpha": 1.0}, ["alpha"]),
        ({"alpha": 0.1, "gamma": -1.0}, ["gamma"]),
        ({"alpha": 0.1, "threshold": 0.9}, ["threshold"]),
    ],
)
def test_a_setting_the_method_does_not_take_is_refused(params, path):
    result = validate_pipeline(boundary_definition(("mad",), params=params))
    found = [item for item in result.issues if item.node_id == "calibrate"]

    assert not result.valid
    assert [item.parameter_path for item in found] == [path]


def test_the_rule_counts_at_least_one_exceedance():
    assert validate_pipeline(
        boundary_definition(("mad",), policy_params={"consecutive": 5})
    ).valid
    result = validate_pipeline(
        boundary_definition(("mad",), policy_params={"consecutive": 0})
    )

    assert [(item.node_id, item.parameter_path) for item in result.issues] == [
        ("policy", ["consecutive"])
    ]


@pytest.mark.parametrize(
    ("detectors", "calibration", "params", "needed"),
    [
        # 1 / 0.01 - 1 scores put a quantile below the largest one.
        (("mad",), "calibrate.aci", {"alpha": 0.01}, 99),
        (("mad",), "calibrate.split", {"alpha": 0.05}, 19),
        # Two detectors under max each reach the top rank once in n scores.
        (("forest", "mad"), "calibrate.aci", {"alpha": 0.01}, 199),
        (("forest", "mad"), "calibrate.aci", {"alpha": 0.01, "fusion": "mean"}, 99),
        # Ranks need the window whatever the method.
        (("forest", "mad"), "calibrate.pid", {"alpha": 0.01}, 199),
    ],
)
def test_a_small_alarm_rate_warns_of_a_short_window(
    detectors, calibration, params, needed
):
    method = calibration.removeprefix("calibrate.")
    fusion = params.get("fusion", "max")
    assert minimum_window(method, params["alpha"], len(detectors), fusion) == needed

    def run(window):
        return validate_pipeline(
            boundary_definition(
                detectors,
                calibration=calibration,
                params=params,
                calibration_window=window,
            )
        )

    short = run(needed - 1)
    assert short.valid
    assert [
        (item.code, item.node_id, item.severity, item.parameter_path)
        for item in short.issues
    ] == [("calibration_window", "calibrate", "warning", ["alpha"])]
    assert f"{needed:,} calibration observations" in short.issues[0].message
    assert run(needed).issues == []


def test_a_method_that_tracks_the_boundary_itself_needs_no_window():
    assert minimum_window("pid", 0.001, 1, "max") == 1
    result = validate_pipeline(
        boundary_definition(
            ("mad",), calibration="calibrate.pid", params={"alpha": 0.001}
        )
    )

    assert result.valid and result.issues == []


def test_a_design_stored_with_a_strategy_can_take_a_step_that_adapts():
    stored = fused_definition("adaptive_stream", fusion="mean", quantile=0.99)
    written = stored.model_dump(mode="json")
    assert written["strategy"] == "adaptive_stream"
    definition = PipelineDefinition.model_validate(written)
    assert definition.strategy is None
    for node in definition.nodes:
        if node.kind == "calibration":
            node.component, node.params = "calibrate.aci", {"alpha": 0.1}
        if node.kind == "policy":
            node.component, node.params = "policy.exceedance", {}

    assert issues(definition) == []
    assert definition.model_dump(mode="json")["strategy"] is None


@pytest.mark.parametrize(
    ("detectors", "settings", "model_type"),
    [
        (("forest",), StaticBaselineConfig, "pyod_iforest"),
        (
            ("mad",),
            AdaptiveStreamConfig,
            "aberrant_moving_average_absolute_deviation",
        ),
        (
            ("forest", "mad"),
            AdaptiveStreamConfig,
            "aberrant_moving_average_absolute_deviation",
        ),
    ],
)
def test_the_run_takes_its_windows_from_the_design(detectors, settings, model_type):
    monitoring = derive_monitoring_config(
        boundary_definition(detectors, policy_params={"consecutive": 3})
    )

    assert isinstance(monitoring, settings)
    assert monitoring.model_type == model_type
    assert monitoring.training_window_size == 30
    assert monitoring.calibration_window_size == 20
    # The rule's own settings stay in the graph: the defaults are untouched.
    defaults = settings(model_type=model_type, model_params=monitoring.model_params)
    policy = (
        "threshold_config"
        if settings is AdaptiveStreamConfig
        else ("martingale_config")
    )
    assert getattr(monitoring, policy) == getattr(defaults, policy)


def test_a_lane_follows_from_how_the_steps_learn():
    def lane(*components):
        return derived_strategy([{"component": item} for item in components])

    forest, mad = (
        "detector:pyod_iforest",
        ("detector:aberrant_moving_average_absolute_deviation"),
    )
    assert lane(forest, "static.standard_scaler") == "static_baseline"
    assert lane(mad, "adaptive.standard_scaler") == "adaptive_stream"
    assert lane(forest, mad) is None
    assert lane("source.aligned") is None


def test_the_alarm_rate_is_a_share_strictly_between_none_and_all():
    model = CALIBRATION_MODELS["calibrate.aci"]

    assert math.isclose(model().alpha, 0.01)
    for value in (0, 1, -0.1, 1.5):
        with pytest.raises(ValueError):
            model(alpha=value)
