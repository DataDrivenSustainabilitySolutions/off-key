"""Allowlisted component metadata, independent of scientific runtime imports."""

from ..schemas.pipelines import (
    NodeKind,
    PipelineCatalog,
    PipelineComponent,
    PipelineDefinition,
    PipelineLayout,
    PipelineStrategy,
    PipelineTemplate,
)
from ..schemas.radar import AdaptiveThresholdConfig, StaticMartingaleConfig
from .adaptive import ADAPTIVE_MODELS_BY_TYPE
from .pipeline_digest import digest
from .pipeline_fields import component_fields
from .pipeline_parameters import PARAMETER_MODELS
from .static import STATIC_MODELS

BOTH: list[PipelineStrategy] = ["static_baseline", "adaptive_stream"]


def pipeline_components() -> list[PipelineComponent]:
    specifications: list[tuple[str, NodeKind, str, str, list[PipelineStrategy]]] = [
        (
            "source.aligned",
            "source",
            "Aligned inputs",
            "One coherent observation of the bound numeric readings.",
            BOTH,
        ),
        (
            "features.select",
            "transform",
            "Select features",
            "Keep selected features in the explicit selection order.",
            BOTH,
        ),
        (
            "features.rename",
            "transform",
            "Rename features",
            "Explicit names prevent collisions when branches merge.",
            BOTH,
        ),
        (
            "features.passthrough",
            "transform",
            "Pass through",
            (
                "Preserve incoming values and names. "
                "Connect directly to aligned inputs to retain raw readings."
            ),
            BOTH,
        ),
        (
            "features.merge",
            "merge",
            "Merge features",
            "Concatenate branches in connection order.",
            BOTH,
        ),
        (
            "static.standard_scaler",
            "transform",
            "Standard scaling",
            "Fit means and variances on training observations only.",
            ["static_baseline"],
        ),
        (
            "static.min_max_scaler",
            "transform",
            "Min-max scaling",
            "Fit bounds on training observations; clipping is explicit.",
            ["static_baseline"],
        ),
        (
            "static.pca",
            "transform",
            "Centered PCA",
            "Batch centered principal components fitted on training data.",
            ["static_baseline"],
        ),
        (
            "static.random_projection",
            "transform",
            "Random projection",
            "A seeded fixed random projection.",
            ["static_baseline"],
        ),
        (
            "adaptive.standard_scaler",
            "transform",
            "Online standard scaling",
            "Score with previous statistics, then update.",
            ["adaptive_stream"],
        ),
        (
            "adaptive.min_max_scaler",
            "transform",
            "Online min-max scaling",
            "Online observed bounds; clipping is explicit.",
            ["adaptive_stream"],
        ),
        (
            "adaptive.uncentered_pca",
            "transform",
            "Online uncentered PCA",
            "Online uncentered components, with explicit initialization.",
            ["adaptive_stream"],
        ),
        (
            "adaptive.random_projection",
            "transform",
            "Random projection",
            "A seeded fixed random projection.",
            ["adaptive_stream"],
        ),
        (
            "policy.martingale",
            "policy",
            "Conformal alarm policy",
            "Existing calibrated martingale alarm policy.",
            ["static_baseline"],
        ),
        (
            "policy.quantile",
            "policy",
            "Calibrated score threshold",
            "Existing frozen empirical quantile alarm policy.",
            ["adaptive_stream"],
        ),
        (
            "output.evidence",
            "output",
            "Evidence and alarms",
            "Persist the existing inference evidence and anomaly output.",
            BOTH,
        ),
    ]
    result = []
    for identifier, kind, label, description, strategies in specifications:
        model = PARAMETER_MODELS.get(identifier)
        schema = (
            model.model_json_schema()
            if model
            else (
                StaticMartingaleConfig
                if identifier == "policy.martingale"
                else AdaptiveThresholdConfig
            ).model_json_schema()
        )
        input_type = (
            None
            if kind == "source"
            else (
                "p_values"
                if identifier == "policy.martingale"
                else "scores"
                if identifier == "policy.quantile"
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
            else "features"
        )
        result.append(
            PipelineComponent(
                id=identifier,
                kind=kind,
                label=label,
                description=description,
                strategies=strategies,
                parameter_schema=schema,
                fields=component_fields(schema),
                input_type=input_type,
                output_type=output_type,
            )
        )
    for identifier, model in STATIC_MODELS.items():
        schema = model.parameters.model_json_schema()
        result.append(
            PipelineComponent(
                id=f"detector:{identifier}",
                kind="detector",
                label=model.name,
                description="Static detector with split-conformal calibration.",
                strategies=["static_baseline"],
                parameter_schema=schema,
                fields=component_fields(schema),
                output_type="p_values",
            )
        )
    for identifier, model in ADAPTIVE_MODELS_BY_TYPE.items():
        schema = model["parameter_schema"]
        result.append(
            PipelineComponent(
                id=f"detector:{identifier}",
                kind="detector",
                label=model["name"],
                description="Adaptive score-before-learn anomaly detector.",
                strategies=["adaptive_stream"],
                parameter_schema=schema,
                fields=component_fields(schema),
                output_type="scores",
            )
        )
    return result


def pipeline_catalog_id() -> str:
    return digest([item.model_dump(mode="json") for item in pipeline_components()])


def pipeline_catalog(authoring_enabled: bool = False) -> PipelineCatalog:
    from .pipeline_compiler import compile_pipeline

    templates = []
    for strategy, detector, policy in [
        ("static_baseline", "pyod_iforest", "martingale"),
        ("adaptive_stream", "aberrant_online_isolation_forest", "quantile"),
    ]:
        definition = PipelineDefinition.model_validate(
            {
                "strategy": strategy,
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
        templates.append(
            PipelineTemplate(
                id=strategy,
                name="Static baseline"
                if strategy == "static_baseline"
                else "Adaptive stream",
                definition=compile_pipeline(definition).definition,
                layout=PipelineLayout(
                    nodes={
                        identifier: {"x": index * 260, "y": 100}
                        for index, identifier in enumerate(
                            ["input", "detector", "policy", "output"]
                        )
                    }
                ),
            )
        )
    return PipelineCatalog(
        catalog_id=pipeline_catalog_id(),
        authoring_enabled=authoring_enabled,
        components=pipeline_components(),
        templates=templates,
    )
