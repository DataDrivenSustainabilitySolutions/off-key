"""What the catalog tells an editor or an agent about each step."""

import json

import pytest
from off_key_core.models.adaptive import ADAPTIVE_MODELS_BY_TYPE
from off_key_core.models.pipeline_guidance import (
    CALIBRATIONS,
    DETECTORS,
    STEPS,
)
from off_key_core.models.pipelines import pipeline_catalog, pipeline_components
from off_key_core.models.static import STATIC_MODELS
from off_key_core.schemas.pipelines import (
    ComponentField,
    FieldCondition,
    PipelineCatalog,
    PipelineComponent,
    shown_when,
)
from pydantic import ValidationError


def _settings(fields: list[ComponentField], parent: str = ""):
    """Every setting of a step, nested ones named with their parents."""
    for field in fields:
        name = f"{parent}{field.name}"
        yield name, field
        yield from _settings(field.fields, f"{name}.")
        for variant in (field.variants or {}).values():
            yield from _settings(variant, f"{name}.")


def test_every_step_and_every_setting_is_described():
    for component in pipeline_components():
        assert component.description.endswith("."), component.id
        # Short enough to choose by in a menu; the rest belongs in details.
        assert len(component.description) <= 170, component.id
        for name, field in _settings(component.fields):
            assert field.description, f"{component.id} {name} has no help"


def test_every_detector_has_a_plain_name_and_its_key_settings():
    detectors = [item for item in pipeline_components() if item.kind == "detector"]
    assert {item.id.removeprefix("detector:") for item in detectors} == set(DETECTORS)
    assert set(DETECTORS) == set(STATIC_MODELS) | set(ADAPTIVE_MODELS_BY_TYPE)
    for component in detectors:
        model_type = component.id.removeprefix("detector:")
        guide = DETECTORS[model_type]
        names = {field.name for field in component.fields}
        # No class names: the library is told apart from the name.
        assert component.label == guide.label
        assert not component.label.startswith(("Aberrant", "PyOD")), component.id
        assert component.library == (
            "PyOD"
            if model_type.startswith("pyod_")
            else "Aberrant"
            if model_type.startswith("aberrant_")
            else None
        )
        # Whatever has settings names the ones worth a first look.
        assert bool(guide.key) == bool(names), component.id
        assert set(guide.key) <= names, component.id
        assert {field.name for field in component.fields if not field.advanced} == set(
            guide.key
        )
        # Help written for a setting that is gone would go unnoticed.
        assert set(guide.settings) <= {name for name, _ in _settings(component.fields)}


def test_guidance_names_only_steps_and_settings_that_exist():
    components = {item.id: item for item in pipeline_components()}
    assert {f"calibrate.{name}" for name in CALIBRATIONS} == {
        item.id
        for item in components.values()
        if item.kind == "calibration" and item.id != "calibrate.fixed_split"
    }
    for identifier, settings in STEPS.items():
        names = {name for name, _ in _settings(components[identifier].fields)}
        assert set(settings) <= names, identifier


def test_a_calibration_method_leads_with_what_it_does_and_keeps_its_formula():
    aci = next(item for item in pipeline_components() if item.id == "calibrate.aci")
    assert aci.description == CALIBRATIONS["aci"]
    assert "alpha_t" in aci.details and "alpha_t" not in aci.description
    assert (aci.family, aci.coverage) == ("conformal", "long_run")


def test_every_step_has_a_group_that_fits_its_kind():
    kinds = {
        "input": {"source"},
        "prepare": {"transform"},
        "combine": {"transform"},
        "normalize": {"transform"},
        "reduce": {"transform"},
        "route": {"transform", "merge"},
        "forecaster": {"detector"},
        "detector": {"detector"},
        "calibration": {"calibration"},
        "policy": {"policy"},
        "output": {"output"},
    }
    components = pipeline_components()
    assert {item.group for item in components} == set(kinds)
    for component in components:
        assert component.kind in kinds[component.group], component.id
        assert (component.group == "forecaster") == (
            component.output_type == "forecasts"
        )
        # Only the steps that learn are normalizers and reducers, except the
        # random projection, whose map is fixed by its seed.
        if component.group == "normalize":
            assert component.learning in ("batch", "online"), component.id


def test_steps_sit_where_an_operator_looks_for_them():
    groups = {item.id: item.group for item in pipeline_components()}

    def of(group: str) -> set[str]:
        return {
            identifier
            for identifier, value in groups.items()
            if value == group and not identifier.startswith("detector:")
        }

    # A step that makes features from others is filed under Combine, and Gate
    # and Mute alarms with the routes, although their identifiers start like a
    # Prepare step.
    assert of("combine") == {
        "prepare.aggregate",
        "prepare.formula",
        "prepare.constant",
        "prepare.condition",
        "prepare.set",
        "prepare.calculate",
    }
    assert of("route") == {
        "features.select",
        "features.rename",
        "features.passthrough",
        "features.merge",
        "prepare.gate",
        "prepare.mute",
    }
    assert {"prepare.hold", "prepare.relation", "prepare.time"} <= of("prepare")
    assert {"static.robust_scaler", "adaptive.robust_scaler"} <= of("normalize")
    # An Expected value leaves one residual in place of the features it uses.
    assert {"static.expected_value", "adaptive.expected_value"} <= of("reduce")
    assert of("forecaster") == {"forecast.timestral"}
    assert groups["detector:aberrant_holt_winters_forecaster"] == "forecaster"
    assert groups["detector:aberrant_seasonal_naive_forecaster"] == "forecaster"
    # The seasonal residual detector has no lead to choose, so it stays a detector.
    assert groups["detector:aberrant_seasonal_residual_detector"] == "detector"


def test_learned_steps_name_the_step_that_learns_the_other_way():
    components = {item.id: item for item in pipeline_components()}
    twins = {
        item.id: item.counterpart for item in components.values() if item.counterpart
    }
    assert twins["static.pca"] == "adaptive.uncentered_pca"
    assert twins["static.expected_value"] == "adaptive.expected_value"
    assert len(twins) == 12
    for identifier, other in twins.items():
        twin = components[other]
        assert twin.counterpart == identifier
        assert (twin.kind, twin.group) == (
            components[identifier].kind,
            components[identifier].group,
        )
        assert identifier.split(".")[0] != other.split(".")[0]


def test_settings_that_depend_on_another_say_so():
    components = {item.id: item for item in pipeline_components()}

    def condition(component: str, setting: str) -> FieldCondition | None:
        fields = {field.name: field for field in components[component].fields}
        found = fields[setting].shown_when
        # The setting it depends on is one of the same step, with that choice.
        if found is not None:
            assert set(found.equals or found.not_equals) <= set(
                fields[found.field].options
            )
        return found

    assert condition("prepare.rolling", "quantile") == FieldCondition(
        field="statistic", equals=["quantile"]
    )
    for setting in ("scale", "offset"):
        assert condition("prepare.math", setting) == FieldCondition(
            field="function", equals=["linear"]
        )
    assert condition("prepare.math", "function") is None
    # A Smooth reads its window or its time constant, whichever its method leaves.
    assert condition("prepare.smooth", "window_size") == FieldCondition(
        field="method", not_equals=["time_constant"]
    )
    assert condition("prepare.smooth", "time_constant") == FieldCondition(
        field="method", equals=["time_constant"]
    )


def test_a_condition_compares_one_way():
    assert shown_when("method", unless=("time_constant",)) == {
        "x-shown-when": {"field": "method", "not_equals": ["time_constant"]}
    }
    assert shown_when("statistic", "quantile", "median") == {
        "x-shown-when": {"field": "statistic", "equals": ["quantile", "median"]}
    }
    for condition in ({"field": "a"}, {"field": "a", "equals": [1], "not_equals": [2]}):
        with pytest.raises(ValidationError):
            FieldCondition.model_validate(condition)


def test_the_listing_leaves_out_what_is_empty_and_reads_back_whole():
    catalog = pipeline_catalog(True)
    written = catalog.model_dump(mode="json")
    smooth = next(
        item for item in written["components"] if item["id"] == "prepare.smooth"
    )
    assert set(smooth) == {
        "id",
        "contract_version",
        "kind",
        "group",
        "label",
        "description",
        "fields",
        "input_type",
        "output_type",
        "learning",
    }
    window = next(field for field in smooth["fields"] if field["name"] == "window_size")
    assert set(window) == {
        "name",
        "label",
        "type",
        "default",
        "has_default",
        "minimum",
        "maximum",
        "description",
        "shown_when",
    }
    # A default of null is still a default, and no input is not "features".
    suffix = next(field for field in smooth["fields"] if field["name"] == "suffix")
    assert suffix["has_default"] and suffix["default"] is None
    source = next(
        item for item in written["components"] if item["id"] == "source.aligned"
    )
    assert source["input_type"] is None
    assert PipelineCatalog.model_validate(written) == catalog
    # About half of what the listing weighed with its schemas and empty keys.
    assert len(json.dumps(written)) < 125_000


def test_a_setting_without_a_default_writes_none():
    field = ComponentField(name="features", label="Features", type="features")
    assert field.model_dump() == {
        "name": "features",
        "label": "Features",
        "type": "features",
    }
    assert (
        "default"
        not in PipelineComponent(
            id="x", kind="transform", group="prepare", label="X", description="X."
        ).model_dump()
    )
