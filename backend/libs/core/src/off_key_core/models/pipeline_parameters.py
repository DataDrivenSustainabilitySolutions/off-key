"""Parameter normalization for the explicitly supported component registry."""

from typing import Any

from ..schemas.pipeline_versions import streams
from ..schemas.pipelines import (
    ExpectedValueParameters,
    FusionMode,
    MinMaxScalerParameters,
    OnlineExpectedValueParameters,
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
from .pipeline_calibration import (
    CALIBRATION_MODELS,
    EXCEEDANCE_RULE,
    ExceedanceRuleParameters,
    Fusion,
)
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
    "static.expected_value": ExpectedValueParameters,
    "adaptive.expected_value": OnlineExpectedValueParameters,
    **PREPARE_MODELS,
    EXCEEDANCE_RULE: ExceedanceRuleParameters,
    "output.evidence": PipelineModel,
}


class MartingalePolicyParameters(StaticMartingaleConfig):
    """The martingale policy of a design, which can combine several detectors."""

    fusion: Fusion = "max"


class ThresholdPolicyParameters(AdaptiveThresholdConfig):
    """The threshold policy of a design, which can combine several detectors."""

    fusion: Fusion = "max"


# The policies of schema 1 designs, which combine the detectors themselves.
# Their schemas lose fusion when the editor shows the calibration step.
POLICY_MODELS = {
    "policy.martingale": MartingalePolicyParameters,
    "policy.quantile": ThresholdPolicyParameters,
}


def policy_settings(params: dict[str, Any]) -> dict[str, Any]:
    """A policy's own settings, without how it combines detectors."""
    return {key: value for key, value in params.items() if key != "fusion"}


def fusion_mode(params: dict[str, Any]) -> FusionMode:
    return params.get("fusion", "max")


def _drop_unread(component: str, params: dict[str, Any]) -> None:
    """Leave out the settings a Prepare step does not read.

    A step that gains a setting then keeps the executable fingerprints of the
    designs that do not use it, and a setting that changes nothing changes no
    fingerprint.
    """
    match component:
        case "prepare.rolling" if params["statistic"] != "quantile":
            params.pop("quantile", None)
        case "prepare.accumulate" if params["reset_when"] is None:
            del params["reset_when"]
        case "prepare.smooth":
            # Smoothing by a time constant reads no window, and the other way round.
            by_time = params["method"] == "time_constant"
            del params["window_size" if by_time else "time_constant"]
        case "prepare.time" if not any(
            params[name] for name in ("hour", "weekday", "daily_cycle", "weekly_cycle")
        ):
            # Only the hour and the weekday follow a time zone.
            del params["timezone"]


def normalized_parameters(
    node: PipelineNode, definition: PipelineDefinition
) -> dict[str, Any]:
    if node.kind == "detector":
        identifier = node.component.removeprefix("detector:")
        # Detectors on the stream score every observation as it arrives.
        if streams(node.component):
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
    _drop_unread(node.component, params)
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
