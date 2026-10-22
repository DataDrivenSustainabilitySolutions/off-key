"""Public lightweight monitoring graph contracts and composition entry points."""

from collections.abc import Mapping, Sequence

from ..schemas.pipelines import BoundInput, PipelineDefinition
from ..schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from .pipeline_catalog import pipeline_catalog, pipeline_catalog_id, pipeline_components
from .pipeline_compiler import compile_pipeline, validate_pipeline
from .pipeline_digest import digest
from .pipeline_parameters import PARAMETER_MODELS

__all__ = [
    "PARAMETER_MODELS",
    "compile_pipeline",
    "derive_monitoring_config",
    "execution_fingerprint",
    "pipeline_catalog",
    "pipeline_catalog_id",
    "pipeline_components",
    "validate_pipeline",
]


def derive_monitoring_config(definition: PipelineDefinition):
    definition = compile_pipeline(definition).definition
    detector = next(node for node in definition.nodes if node.kind == "detector")
    policy = next(node for node in definition.nodes if node.kind == "policy")
    common = dict(
        model_type=detector.component.removeprefix("detector:"),
        model_params=detector.params,
        training_window_size=definition.settings.training_window_size,
        calibration_window_size=definition.settings.calibration_window_size,
    )
    if definition.strategy == "adaptive_stream":
        return AdaptiveStreamConfig(**common, threshold_config=policy.params)
    return StaticBaselineConfig(
        **common,
        seed=definition.settings.seed,
        conformal_strategy=definition.settings.conformal_strategy,
        martingale_config=policy.params,
    )


def execution_fingerprint(
    definition: PipelineDefinition, bindings: Sequence[BoundInput | Mapping]
) -> str:
    normalized = [
        BoundInput.model_validate(item).model_dump(mode="json") for item in bindings
    ]
    return digest(
        {
            "graph": compile_pipeline(definition).fingerprint,
            "bindings": sorted(normalized, key=lambda item: item["slot_id"]),
        }
    )
