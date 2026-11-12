"""Allowlisted component metadata, independent of scientific runtime imports."""

from copy import deepcopy
from functools import cache
from typing import Any

from pydantic import BaseModel

from ..schemas.pipeline_versions import (
    CALIBRATION_PREFIX,
    FIXED_SPLIT,
    component_learning,
)
from ..schemas.pipelines import (
    NodeKind,
    PipelineCatalog,
    PipelineComponent,
    PipelineDefinition,
    PipelineLayout,
    PipelineTemplate,
)
from ..schemas.radar import AdaptiveThresholdConfig, StaticMartingaleConfig
from .adaptive import ADAPTIVE_MODELS_BY_TYPE, detector_component
from .pipeline_calibration import CALIBRATION_MODELS, CALIBRATORS, EXCEEDANCE_RULE
from .pipeline_digest import digest
from .pipeline_fields import component_fields
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


def pipeline_components() -> list[PipelineComponent]:
    specifications: list[tuple[str, NodeKind, str, str]] = [
        (
            "source.aligned",
            "source",
            "Aligned inputs",
            "One coherent observation of the bound numeric readings.",
        ),
        (
            "features.select",
            "transform",
            "Select features",
            "Keep selected features in the explicit selection order.",
        ),
        (
            "features.rename",
            "transform",
            "Rename features",
            "Explicit names prevent collisions when branches merge.",
        ),
        (
            "features.passthrough",
            "transform",
            "Pass through",
            (
                "Preserve incoming values and names. "
                "Connect directly to aligned inputs to retain raw readings."
            ),
        ),
        (
            "features.merge",
            "merge",
            "Merge features",
            "Concatenate branches in connection order.",
        ),
        (
            "prepare.smooth",
            "transform",
            "Smooth",
            "Average recent values, exponentially or over a window.",
        ),
        (
            "prepare.despike",
            "transform",
            "Despike",
            "Replace values far from the recent median with the median.",
        ),
        (
            "prepare.change",
            "transform",
            "Change",
            "Difference, percent change or the value a few observations back.",
        ),
        (
            "prepare.rolling",
            "transform",
            "Rolling statistic",
            "Sum, quantile, spread, trend, shape and scores of recent values.",
        ),
        (
            "prepare.math",
            "transform",
            "Math",
            "log, log1p, square root, absolute value, square or scale and offset.",
        ),
        (
            "prepare.range",
            "transform",
            "Range check",
            "Clip values to a range, or skip observations outside it.",
        ),
        (
            "prepare.aggregate",
            "transform",
            "Aggregate",
            "Mean, sum, minimum, maximum, spread or range across features.",
        ),
        (
            "prepare.formula",
            "transform",
            "Formula",
            "One feature computed from the features arriving here.",
        ),
        (
            "prepare.gate",
            "transform",
            "Gate",
            "Learn and score only the observations where a condition holds.",
        ),
        (
            "prepare.constant",
            "transform",
            "Constant",
            "Add a named constant for later calculations and conditions.",
        ),
        (
            "prepare.condition",
            "transform",
            "Condition",
            "Add a 1 or 0 feature from a condition, keeping every observation.",
        ),
        (
            "prepare.set",
            "transform",
            "Set feature",
            "Compute or replace one named feature, preserving the others.",
        ),
        (
            "prepare.accumulate",
            "transform",
            "Accumulate",
            "Keep a running total, minimum or maximum of accepted values.",
        ),
        (
            "static.standard_scaler",
            "transform",
            "Standard scaling",
            "Fit means and variances on training observations only.",
        ),
        (
            "static.min_max_scaler",
            "transform",
            "Min-max scaling",
            "Fit bounds on training observations; clipping is explicit.",
        ),
        (
            "static.robust_scaler",
            "transform",
            "Robust scaling",
            "Center on the training median and divide by its interquartile range.",
        ),
        (
            "static.pca",
            "transform",
            "Centered PCA",
            "Batch centered principal components fitted on training data.",
        ),
        (
            "static.random_projection",
            "transform",
            "Random projection",
            "A seeded fixed random projection.",
        ),
        (
            "adaptive.standard_scaler",
            "transform",
            "Online standard scaling",
            "Score with previous statistics, then update.",
        ),
        (
            "adaptive.min_max_scaler",
            "transform",
            "Online min-max scaling",
            "Online observed bounds; clipping is explicit.",
        ),
        (
            "adaptive.robust_scaler",
            "transform",
            "Online robust scaling",
            "Center on the recent median and divide by the recent interquartile range.",
        ),
        (
            "adaptive.uncentered_pca",
            "transform",
            "Online uncentered PCA",
            "Online uncentered components, with explicit initialization.",
        ),
        (
            "adaptive.random_projection",
            "transform",
            "Random projection",
            "A seeded fixed random projection.",
        ),
        (
            FIXED_SPLIT,
            "calibration",
            "Fixed split",
            (
                "Freeze each detector's scores on the calibration window and rank "
                "every later score against them."
            ),
        ),
        *(
            (
                f"{CALIBRATION_PREFIX}{identifier}",
                "calibration",
                method["name"],
                method["summary"],
            )
            for identifier, method in CALIBRATORS.items()
        ),
        (
            "policy.martingale",
            "policy",
            "Conformal alarm policy",
            "Existing calibrated martingale alarm policy.",
        ),
        (
            "policy.quantile",
            "policy",
            "Calibrated score threshold",
            "Existing frozen empirical quantile alarm policy.",
        ),
        (
            EXCEEDANCE_RULE,
            "policy",
            "Exceedance rule",
            "Alarm when scores stay above the boundary a calibration step adapts.",
        ),
        (
            "output.evidence",
            "output",
            "Evidence and alarms",
            "Persist the existing inference evidence and anomaly output.",
        ),
    ]
    result = []
    for identifier, kind, label, description in specifications:
        schema = _json_schema(
            PARAMETER_MODELS.get(identifier)
            or CALIBRATION_MODELS.get(identifier)
            or _POLICY_SCHEMAS[identifier]
        )
        input_type = (
            None
            if kind == "source"
            else (
                "scores"
                if kind == "calibration"
                else "p_values"
                if kind == "policy"
                else "decisions"
                if kind == "output"
                else "features"
            )
        )
        output_type = (
            "decisions"
            if kind == "policy"
            else "evidence"
            if kind == "output"
            else "p_values"
            if kind == "calibration"
            else "features"
        )
        result.append(
            PipelineComponent(
                id=identifier,
                kind=kind,
                label=label,
                description=description,
                learning=component_learning(identifier),
                parameter_schema=schema,
                fields=component_fields(schema),
                input_type=input_type,
                output_type=output_type,
                **_calibration_facts(identifier),
            )
        )
    for identifier, model in STATIC_MODELS.items():
        schema = _json_schema(model.parameters)
        result.append(
            PipelineComponent(
                id=f"detector:{identifier}",
                kind="detector",
                label=model.name,
                description="Detector fitted once on the training window.",
                learning="batch",
                parameter_schema=schema,
                fields=component_fields(schema),
                output_type="scores",
            )
        )
    for identifier, model in ADAPTIVE_MODELS_BY_TYPE.items():
        schema = model["parameter_schema"]
        result.append(
            PipelineComponent(
                id=detector_component(identifier),
                kind="detector",
                label=model["name"],
                description=(
                    "Scores a feature by how far it misses its forecast."
                    if "forecaster_id" in model
                    else "Adaptive score-before-learn anomaly detector."
                ),
                learning=component_learning(detector_component(identifier)),
                parameter_schema=schema,
                fields=component_fields(schema),
                # A forecaster hands its forecast on with the score, so the
                # calibration step can give the band its boundary leaves.
                output_type="forecasts" if "forecaster_id" in model else "scores",
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
    return PipelineCatalog(
        catalog_id=_catalog_id(pipeline_components()),
        authoring_enabled=authoring_enabled,
        components=pipeline_components(),
        templates=templates,
    )
