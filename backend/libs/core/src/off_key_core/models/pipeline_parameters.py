"""Parameter normalization for the explicitly supported component registry."""

from typing import Any

from ..schemas.pipelines import (
    MinMaxScalerParameters,
    OnlinePCAParameters,
    PipelineDefinition,
    PipelineModel,
    PipelineNode,
    ProjectionParameters,
    RenameParameters,
    SelectParameters,
    StandardScalerParameters,
)
from ..schemas.radar import AdaptiveThresholdConfig, StaticMartingaleConfig
from .adaptive import validate_adaptive_model_params
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
    "static.pca": ProjectionParameters,
    "static.random_projection": ProjectionParameters,
    "adaptive.random_projection": ProjectionParameters,
    "adaptive.uncentered_pca": OnlinePCAParameters,
    "output.evidence": PipelineModel,
}
POLICY_MODELS = {
    "policy.martingale": StaticMartingaleConfig,
    "policy.quantile": AdaptiveThresholdConfig,
}


def normalized_parameters(
    node: PipelineNode, definition: PipelineDefinition
) -> dict[str, Any]:
    if node.kind == "detector":
        identifier = node.component.removeprefix("detector:")
        if definition.strategy == "adaptive_stream":
            return validate_adaptive_model_params(identifier, node.params)
        return validate_static_model_params(
            identifier, node.params, include_defaults=True
        )
    model = POLICY_MODELS.get(node.component) or PARAMETER_MODELS[node.component]
    params = model.model_validate(node.params).model_dump(mode="json")
    if "seed" in params and params["seed"] is None:
        params["seed"] = definition.settings.seed
    return params
