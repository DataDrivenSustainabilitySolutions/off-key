"""Static detector catalog shared by API validation and the RADAR runtime.

Only RADAR imports these numerical implementations. Registry metadata cannot
change executable code or its parameter contract.
"""

from dataclasses import dataclass
from typing import Any

from .static_params import (
    ModelHyperparameters,
    PyODHBOSParams,
    PyODIsolationForestParams,
    PyODKNNParams,
    PyODLOFParams,
    PyODOCSVMParams,
    PyODPCAParams,
)


@dataclass(frozen=True)
class StaticModelDefinition:
    name: str
    import_path: str
    parameters: type[ModelHyperparameters]
    complexity: str = "medium"
    memory_usage: str = "medium"


STATIC_MODELS = {
    "pyod_iforest": StaticModelDefinition(
        "PyOD Isolation Forest",
        "pyod.models.iforest.IForest",
        PyODIsolationForestParams,
    ),
    "pyod_knn": StaticModelDefinition("PyOD KNN", "pyod.models.knn.KNN", PyODKNNParams),
    "pyod_lof": StaticModelDefinition(
        "PyOD Local Outlier Factor",
        "pyod.models.lof.LOF",
        PyODLOFParams,
    ),
    "pyod_ocsvm": StaticModelDefinition(
        "PyOD One-Class SVM",
        "pyod.models.ocsvm.OCSVM",
        PyODOCSVMParams,
        complexity="high",
    ),
    "pyod_hbos": StaticModelDefinition(
        "PyOD HBOS",
        "pyod.models.hbos.HBOS",
        PyODHBOSParams,
        complexity="low",
        memory_usage="low",
    ),
    "pyod_pca": StaticModelDefinition("PyOD PCA", "pyod.models.pca.PCA", PyODPCAParams),
}


def get_static_model_definition(model_type: str) -> StaticModelDefinition:
    try:
        return STATIC_MODELS[model_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported static PyOD model '{model_type}'") from exc


def validate_static_model_params(
    model_type: str,
    params: dict[str, Any],
    *,
    include_defaults: bool = True,
) -> dict[str, Any]:
    definition = get_static_model_definition(model_type)
    return definition.parameters.model_validate(params, strict=True).model_dump(
        exclude_unset=not include_defaults,
    )
