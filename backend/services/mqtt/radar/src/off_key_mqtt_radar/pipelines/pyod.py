"""PyOD detectors fitted once, and their split conformal calibration."""

from __future__ import annotations

import importlib
from typing import Any

from off_key_core.models.static import (
    get_static_model_definition,
    validate_static_model_params,
)


def seeded_params(
    model_type: str, params: dict[str, Any], seed: int | None
) -> dict[str, Any]:
    """The run's seed as the detector's random state, unless one is set."""
    definition = get_static_model_definition(model_type)
    if seed is not None and "random_state" in definition.parameters.model_fields:
        params.setdefault("random_state", seed)
    return params


def instantiate_pyod(model_type: str, params: dict[str, Any]) -> Any:
    definition = get_static_model_definition(model_type)
    module, _, name = definition.import_path.rpartition(".")
    detector_class = getattr(importlib.import_module(module), name)
    return detector_class(
        **validate_static_model_params(model_type, params, include_defaults=False)
    )


def node_detector(node, seed: int | None) -> Any:
    """One detector node of the graph, without its parameters' defaults."""
    model_type = node.component.removeprefix("detector:")
    params = validate_static_model_params(
        model_type, node.params, include_defaults=False
    )
    return instantiate_pyod(model_type, seeded_params(model_type, params, seed))


def calibrated_detector(detector, training, calibration, seed: int | None):
    """Fit on the training matrix and keep the calibration matrix's scores."""
    from nonconform import ConformalDetector, Split

    detector.fit(training)
    conformal_detector = ConformalDetector(
        detector=detector,
        strategy=Split(n_calib=0.1),
        score_polarity="auto",
        seed=seed,
    )
    return conformal_detector.calibrate(calibration)
