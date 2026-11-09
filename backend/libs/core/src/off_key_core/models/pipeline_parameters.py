"""Parameter normalization for the explicitly supported component registry."""

from typing import Annotated, Any

from pydantic import Field

from ..schemas.pipeline_versions import FIXED_SPLIT, component_learning
from ..schemas.pipelines import (
    FusionMode,
    MinMaxScalerParameters,
    OnlinePCAParameters,
    PipelineDefinition,
    PipelineModel,
    PipelineNode,
    ProjectionParameters,
    RenameParameters,
    RobustScalerParameters,
    RollingRobustScalerParameters,
    SelectParameters,
    StandardScalerParameters,
)
from ..schemas.radar import AdaptiveThresholdConfig, StaticMartingaleConfig
from .adaptive import validate_adaptive_model_params
from .pipeline_prepare import PREPARE_MODELS
from .pipeline_scope import SCOPED_COMPONENTS, canonical_scope
from .static import validate_static_model_params

PARAMETER_MODELS: dict[str, type[PipelineModel]] = {
    "source.aligned": PipelineModel,
    "features.passthrough": PipelineModel,
    "features.merge": PipelineModel,
    "features.select": SelectParameters,
    "features.rename": RenameParameters,
    "static.standard_scaler": StandardScalerParameters,
    "adaptive.standard_scaler": StandardScalerParameters,
    "static.min_max_scaler": MinMaxScalerParameters,
    "adaptive.min_max_scaler": MinMaxScalerParameters,
    "static.robust_scaler": RobustScalerParameters,
    "adaptive.robust_scaler": RollingRobustScalerParameters,
    "static.pca": ProjectionParameters,
    "static.random_projection": ProjectionParameters,
    "adaptive.random_projection": ProjectionParameters,
    "adaptive.uncentered_pca": OnlinePCAParameters,
    **PREPARE_MODELS,
    "output.evidence": PipelineModel,
}
Fusion = Annotated[
    FusionMode,
    Field(
        title="Combine detectors",
        description=(
            "How several detectors raise one alarm. Each score becomes a surprise "
            "against that detector's calibration scores; max follows the strongest "
            "surprise, mean their average. With one detector this has no effect."
        ),
    ),
]


class MartingalePolicyParameters(StaticMartingaleConfig):
    """The martingale policy of a design, which can combine several detectors."""

    fusion: Fusion = "max"


class ThresholdPolicyParameters(AdaptiveThresholdConfig):
    """The threshold policy of a design, which can combine several detectors."""

    fusion: Fusion = "max"


class CalibrationParameters(PipelineModel):
    """How a calibration step combines the detectors that feed it."""

    fusion: Fusion = "max"


POLICY_MODELS = {
    "policy.martingale": MartingalePolicyParameters,
    "policy.quantile": ThresholdPolicyParameters,
}
# The policies' schemas lose fusion when the editor shows the calibration step.
CALIBRATION_MODELS: dict[str, type[PipelineModel]] = {
    FIXED_SPLIT: CalibrationParameters,
}


def policy_settings(params: dict[str, Any]) -> dict[str, Any]:
    """A policy's own settings, without how it combines detectors."""
    return {key: value for key, value in params.items() if key != "fusion"}


def fusion_mode(params: dict[str, Any]) -> FusionMode:
    return params.get("fusion", "max")


def normalized_parameters(
    node: PipelineNode, definition: PipelineDefinition
) -> dict[str, Any]:
    if node.kind == "detector":
        identifier = node.component.removeprefix("detector:")
        if component_learning(node.component) == "online":
            return validate_adaptive_model_params(identifier, node.params)
        return validate_static_model_params(
            identifier, node.params, include_defaults=True
        )
    model = (
        POLICY_MODELS.get(node.component)
        or CALIBRATION_MODELS.get(node.component)
        or PARAMETER_MODELS[node.component]
    )
    params = model.model_validate(node.params).model_dump(mode="json")
    if node.component in POLICY_MODELS:
        # The calibration step combines detectors now; schema 1 designs move
        # their setting there when they are read.
        del params["fusion"]
    if node.component in CALIBRATION_MODELS and (
        params["fusion"] == "max"
        or sum(item.kind == "detector" for item in definition.nodes) < 2
    ):
        # Left out at its default and with one detector, so designs that do
        # not combine detectors keep their fingerprints.
        del params["fusion"]
    if "seed" in params and params["seed"] is None:
        params["seed"] = definition.settings.seed
    if node.component in SCOPED_COMPONENTS:
        return canonical_scope(node.component, params)
    return params
