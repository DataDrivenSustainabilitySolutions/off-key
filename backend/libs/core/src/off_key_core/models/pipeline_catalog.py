"""Allowlisted component metadata, independent of scientific runtime imports."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from typing import Any

from pydantic import BaseModel

from ..schemas.pipeline_versions import (
    CALIBRATION_PREFIX,
    FIXED_SPLIT,
    component_learning,
)
from ..schemas.pipelines import (
    ComponentField,
    Learning,
    NodeKind,
    PipelineCatalog,
    PipelineComponent,
    PipelineDefinition,
    PipelineLayout,
    PipelineTemplate,
    PortType,
    StepGroup,
)
from ..schemas.radar import AdaptiveThresholdConfig, StaticMartingaleConfig
from .adaptive import ADAPTIVE_MODELS_BY_TYPE, detector_component
from .pipeline_calibration import CALIBRATION_MODELS, CALIBRATORS, EXCEEDANCE_RULE
from .pipeline_digest import digest
from .pipeline_fields import component_fields
from .pipeline_guidance import (
    CALIBRATIONS,
    DETECTORS,
    SETTINGS,
    STEPS,
    library,
)
from .pipeline_parameters import PARAMETER_MODELS
from .static import STATIC_MODELS

# Schema 2 policies: the calibration step combines the detectors.
_POLICY_SCHEMAS: dict[str, type[BaseModel]] = {
    "policy.martingale": StaticMartingaleConfig,
    "policy.quantile": AdaptiveThresholdConfig,
}


@cache
def _generated_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _json_schema(model: type[BaseModel]) -> dict[str, Any]:
    # Generation dominates catalogue builds; the copy keeps each caller's dict private.
    return deepcopy(_generated_schema(model))


@dataclass(frozen=True)
class _Step:
    id: str
    kind: NodeKind
    group: StepGroup
    label: str
    # One sentence for whoever chooses the step: what it does to the data.
    description: str
    # What is worth knowing beyond that sentence.
    details: str = ""


_STEPS: tuple[_Step, ...] = (
    _Step(
        "source.aligned",
        "source",
        "input",
        "Aligned inputs",
        "The chosen readings as one observation.",
    ),
    _Step(
        "features.select",
        "transform",
        "route",
        "Select features",
        "Keep only the chosen features.",
        "The features leave in the order they are chosen.",
    ),
    _Step(
        "features.rename",
        "transform",
        "route",
        "Rename features",
        "Give features new names.",
        "Distinct names keep branches from colliding where they merge.",
    ),
    _Step(
        "features.passthrough",
        "transform",
        "route",
        "Pass through",
        "Forward features unchanged.",
        "Connected to the input, it carries the raw readings past other steps.",
    ),
    _Step(
        "features.merge",
        "merge",
        "route",
        "Merge features",
        "Join branches into one feature list.",
        "The features follow the order of the connections.",
    ),
    _Step(
        "prepare.smooth",
        "transform",
        "prepare",
        "Smooth",
        "Average recent values to calm noise, over observations or over time.",
    ),
    _Step(
        "prepare.despike",
        "transform",
        "prepare",
        "Despike",
        "Replace sudden spikes with the recent median.",
    ),
    _Step(
        "prepare.change",
        "transform",
        "prepare",
        "Change",
        "Add the change since earlier observations.",
    ),
    _Step(
        "prepare.rolling",
        "transform",
        "prepare",
        "Rolling statistic",
        "Add a sum, quantile, spread, trend, shape or score of recent values.",
    ),
    _Step(
        "prepare.math",
        "transform",
        "prepare",
        "Math",
        "Take a log, root, absolute value, square or scale.",
    ),
    _Step(
        "prepare.range",
        "transform",
        "prepare",
        "Range check",
        "Clip values to a range, or skip observations outside it.",
    ),
    _Step(
        "prepare.aggregate",
        "transform",
        "combine",
        "Aggregate",
        "Combine features into their mean, sum, extreme, spread or range.",
    ),
    _Step(
        "prepare.formula",
        "transform",
        "combine",
        "Formula",
        "Compute a feature from others, such as dc_voltage * dc_current.",
    ),
    # A Gate decides whether an observation goes on, so it sits with the routes.
    _Step(
        "prepare.gate",
        "transform",
        "route",
        "Gate",
        "Learn and score only while a condition holds.",
    ),
    # Mute alarms decides whether an observation may alarm, so it sits there too.
    _Step(
        "prepare.mute",
        "transform",
        "route",
        "Mute alarms",
        "Raise no alarm while a condition holds.",
        "Learning and scoring go on, unlike at a Gate.",
    ),
    _Step(
        "prepare.constant",
        "transform",
        "combine",
        "Constant",
        "Add a named constant to use in later steps.",
    ),
    _Step(
        "prepare.condition",
        "transform",
        "combine",
        "Condition",
        "Turn a comparison or Boolean condition into a 1 or 0 feature.",
        "Every observation goes on, unlike at a Gate.",
    ),
    _Step(
        "prepare.set",
        "transform",
        "combine",
        "Set feature",
        "Calculate or replace one feature, keeping the others.",
    ),
    _Step(
        "prepare.accumulate",
        "transform",
        "prepare",
        "Accumulate",
        "Keep a running total, minimum, maximum or count, "
        "and start over on a condition.",
    ),
    _Step(
        "prepare.hold",
        "transform",
        "prepare",
        "Hold",
        "Keep each value from the last time a condition held.",
    ),
    _Step(
        "prepare.relation",
        "transform",
        "prepare",
        "Rolling relation",
        "Add how features move with one other feature: correlation, slope or residual.",
    ),
    _Step(
        "prepare.calculate",
        "transform",
        "combine",
        "Calculate",
        "Calculate several named features, one formula per line.",
        "The lines run in order, so a line can read the features above it.",
    ),
    _Step(
        "prepare.time",
        "transform",
        "prepare",
        "Time features",
        "Add the seconds since the previous observation, the hour or the weekday.",
    ),
    _Step(
        "static.standard_scaler",
        "transform",
        "normalize",
        "Standard scaling",
        "Center and scale with training statistics.",
        "Means and variances are fitted on the training window and then stay.",
    ),
    _Step(
        "static.min_max_scaler",
        "transform",
        "normalize",
        "Min-max scaling",
        "Scale to 0 to 1 with training bounds.",
        "Later values beyond the training bounds leave 0 to 1 unless clipped.",
    ),
    _Step(
        "static.robust_scaler",
        "transform",
        "normalize",
        "Robust scaling",
        "Center on the median and divide by the quartile range of training data.",
    ),
    _Step(
        "static.pca",
        "transform",
        "reduce",
        "Centered PCA",
        "Keep the main directions of the training data.",
        "Centered principal components, fitted on the training window.",
    ),
    _Step(
        "static.random_projection",
        "transform",
        "reduce",
        "Random projection",
        "Fewer dimensions through a fixed random map.",
        "The map follows from the seed alone, so nothing is learned.",
    ),
    # An Expected value leaves one residual in place of the features it uses.
    _Step(
        "static.expected_value",
        "transform",
        "reduce",
        "Expected value",
        "Give how far one feature is from what the others imply, "
        "by a fit on training data.",
    ),
    _Step(
        "adaptive.standard_scaler",
        "transform",
        "normalize",
        "Online standard scaling",
        "Center and scale with running statistics.",
        "Each observation is scaled with the statistics before it, then joins them.",
    ),
    _Step(
        "adaptive.min_max_scaler",
        "transform",
        "normalize",
        "Online min-max scaling",
        "Scale to 0 to 1 with the bounds seen so far.",
        "A value beyond the bounds so far leaves 0 to 1 unless clipped.",
    ),
    _Step(
        "adaptive.robust_scaler",
        "transform",
        "normalize",
        "Online robust scaling",
        "Center on the recent median and divide by the recent quartile range.",
    ),
    _Step(
        "adaptive.uncentered_pca",
        "transform",
        "reduce",
        "Online uncentered PCA",
        "Keep the main directions, updated as data arrives.",
        "The components are taken around zero. Center or standardize the "
        "features first for a conventional PCA.",
    ),
    _Step(
        "adaptive.random_projection",
        "transform",
        "reduce",
        "Random projection",
        "Fewer dimensions through a fixed random map.",
        "The map follows from the seed alone, so nothing is learned.",
    ),
    _Step(
        "adaptive.expected_value",
        "transform",
        "reduce",
        "Online expected value",
        "Give how far one feature is from what the others imply, "
        "by a fit updated as data arrives.",
        "Each observation is compared with the fit before it, then joins it.",
    ),
    _Step(
        FIXED_SPLIT,
        "calibration",
        "calibration",
        "Fixed split",
        "Rank every score against the calibration window, which then stays as it is.",
    ),
    *(
        _Step(
            f"{CALIBRATION_PREFIX}{identifier}",
            "calibration",
            "calibration",
            method["name"],
            CALIBRATIONS[identifier],
            method["summary"],
        )
        for identifier, method in CALIBRATORS.items()
    ),
    _Step(
        "policy.martingale",
        "policy",
        "policy",
        "Conformal alarm policy",
        "Alarm when evidence of change builds up.",
        "A conformal martingale over the p-values of a fixed split.",
    ),
    _Step(
        "policy.quantile",
        "policy",
        "policy",
        "Calibrated score threshold",
        "Alarm when scores pass a calibrated threshold.",
        "The threshold is a quantile of the calibration scores and then stays.",
    ),
    _Step(
        EXCEEDANCE_RULE,
        "policy",
        "policy",
        "Exceedance rule",
        "Alarm when scores stay above the boundary the calibration step adapts.",
    ),
    _Step(
        "output.evidence",
        "output",
        "output",
        "Evidence and alarms",
        "Store scores, evidence and alarms.",
    ),
)

# Learned steps that do the same job fitted once and learning continuously.
_COUNTERPARTS: tuple[tuple[str, str], ...] = (
    ("static.standard_scaler", "adaptive.standard_scaler"),
    ("static.min_max_scaler", "adaptive.min_max_scaler"),
    ("static.robust_scaler", "adaptive.robust_scaler"),
    ("static.pca", "adaptive.uncentered_pca"),
    ("static.random_projection", "adaptive.random_projection"),
    ("static.expected_value", "adaptive.expected_value"),
)
_COUNTERPART = {
    one: other
    for fitted, continuous in _COUNTERPARTS
    for one, other in ((fitted, continuous), (continuous, fitted))
}

_PORTS: dict[NodeKind, tuple[PortType | None, PortType]] = {
    "source": (None, "features"),
    "transform": ("features", "features"),
    "merge": ("features", "features"),
    "calibration": ("scores", "p_values"),
    "policy": ("p_values", "decisions"),
    "output": ("decisions", "evidence"),
}


def _guided(
    fields: list[ComponentField],
    settings: Mapping[str, str],
    key: tuple[str, ...] | None = None,
    parent: str = "",
) -> list[ComponentField]:
    """Settings with the composer's help where their schema has none.

    A detector names its key settings; all its others are advanced, and help
    shared by a setting's name fills what is still empty.
    """
    result = []
    for item in fields:
        name = f"{parent}{item.name}"
        update: dict[str, Any] = {
            "description": settings.get(name)
            or item.description
            or (SETTINGS.get(item.name, "") if key is not None else ""),
            "fields": _guided(item.fields, settings, key, f"{name}."),
        }
        if item.variants is not None:
            update["variants"] = {
                choice: _guided(variant, settings, key, f"{name}.")
                for choice, variant in item.variants.items()
            }
        if key is not None and not parent:
            update["advanced"] = name not in key
        result.append(item.model_copy(update=update))
    return result


def detector_fields(model_type: str, schema: dict[str, Any]) -> list[ComponentField]:
    """A detector's settings as every editor shows them, with their help."""
    guide = DETECTORS[model_type]
    return _guided(component_fields(schema), guide.settings, guide.key)


def _detector(
    model_type: str,
    identifier: str,
    schema: dict[str, Any],
    learning: Learning,
    output_type: PortType,
) -> PipelineComponent:
    guide = DETECTORS[model_type]
    return PipelineComponent(
        id=identifier,
        kind="detector",
        group="forecaster" if output_type == "forecasts" else "detector",
        label=guide.label,
        description=guide.description,
        library=library(model_type),
        learning=learning,
        parameter_schema=schema,
        fields=detector_fields(model_type, schema),
        output_type=output_type,
    )


def pipeline_components() -> list[PipelineComponent]:
    result = []
    for step in _STEPS:
        schema = _json_schema(
            PARAMETER_MODELS.get(step.id)
            or CALIBRATION_MODELS.get(step.id)
            or _POLICY_SCHEMAS[step.id]
        )
        input_type, output_type = _PORTS[step.kind]
        result.append(
            PipelineComponent(
                id=step.id,
                kind=step.kind,
                group=step.group,
                label=step.label,
                description=step.description,
                details=step.details,
                learning=component_learning(step.id),
                counterpart=_COUNTERPART.get(step.id),
                parameter_schema=schema,
                fields=_guided(component_fields(schema), STEPS.get(step.id, {})),
                input_type=input_type,
                output_type=output_type,
                **_calibration_facts(step.id),
            )
        )
    for identifier, model in STATIC_MODELS.items():
        result.append(
            _detector(
                identifier,
                f"detector:{identifier}",
                _json_schema(model.parameters),
                "batch",
                "scores",
            )
        )
    for identifier, model in ADAPTIVE_MODELS_BY_TYPE.items():
        component = detector_component(identifier)
        result.append(
            _detector(
                identifier,
                component,
                model["parameter_schema"],
                component_learning(component),
                # A forecaster hands its forecast on with the score, so the
                # calibration step can give the band its boundary leaves.
                "forecasts" if "forecaster_id" in model else "scores",
            )
        )
    return result


def _calibration_facts(identifier: str) -> dict[str, Any]:
    """What a calibration step's card says about its method."""
    if identifier == FIXED_SPLIT:
        return {"family": "conformal", "coverage": "exchangeable"}
    method = CALIBRATORS.get(identifier.removeprefix(CALIBRATION_PREFIX))
    if method is None or not identifier.startswith(CALIBRATION_PREFIX):
        return {}
    return {
        "family": method["family"],
        "coverage": method["coverage"],
        "reference": method["reference"],
    }


def _catalog_id(components: list[PipelineComponent]) -> str:
    return digest([item.model_dump(mode="json") for item in components])


def pipeline_catalog_id() -> str:
    return _catalog_id(pipeline_components())


def pipeline_catalog(authoring_enabled: bool = False) -> PipelineCatalog:
    from .pipeline_compiler import compile_pipeline

    templates = []
    for identifier, name, detector, policy in [
        ("static_baseline", "Static baseline", "pyod_iforest", "martingale"),
        (
            "adaptive_stream",
            "Adaptive stream",
            "aberrant_online_isolation_forest",
            "quantile",
        ),
    ]:
        definition = PipelineDefinition.model_validate(
            {
                "input_slots": [{"id": "value", "label": "Value"}],
                "nodes": [
                    {"id": "input", "kind": "source", "component": "source.aligned"},
                    {
                        "id": "detector",
                        "kind": "detector",
                        "component": f"detector:{detector}",
                    },
                    {"id": "policy", "kind": "policy", "component": f"policy.{policy}"},
                    {"id": "output", "kind": "output", "component": "output.evidence"},
                ],
                "edges": [
                    {"source": "input", "target": "detector"},
                    {"source": "detector", "target": "policy"},
                    {"source": "policy", "target": "output"},
                ],
            }
        )
        compiled = compile_pipeline(definition).definition
        templates.append(
            PipelineTemplate(
                id=identifier,
                name=name,
                definition=compiled,
                # 64px between cards leaves every wire room for the editor's
                # insert handle beside the 28px connection dots.
                layout=PipelineLayout(
                    nodes={
                        node.id: {"x": index * 288, "y": 100}
                        for index, node in enumerate(compiled.nodes)
                    }
                ),
            )
        )
    components = pipeline_components()
    return PipelineCatalog(
        catalog_id=_catalog_id(components),
        authoring_enabled=authoring_enabled,
        # The settings say what an editor needs. The JSON schema they are
        # compiled from doubles the listing, so one component is read with it.
        components=[
            component.model_copy(update={"parameter_schema": {}})
            for component in components
        ],
        templates=templates,
    )


def pipeline_component(identifier: str) -> PipelineComponent | None:
    """One component as the catalog lists it, with its parameter schema."""
    return next((item for item in pipeline_components() if item.id == identifier), None)
