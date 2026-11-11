"""The detector service that runs a monitor's design.

A calibration step that keeps adapting runs under its boundary, whatever its
detectors. Otherwise the policy picks the settings: the conformal alarm policy
runs a static baseline. A threshold run whose detectors all take in every
observation is an adaptive stream; one that also has detectors fitted once
runs them side by side, meeting at the fixed split.
"""

from off_key_core.models.pipeline_calibration import calibrator_id
from off_key_core.schemas.pipeline_versions import component_learning

from .adaptive_detector import AdaptiveStreamDetectionService
from .boundary_detector import BoundaryDetectionService
from .detector import StaticConformalDetectionService
from .mixed_detector import MixedDetectionService


def detector_service_class(config):
    nodes = config.pipeline.definition.nodes
    if any(
        node.kind == "calibration" and calibrator_id(node.component) is not None
        for node in nodes
    ):
        return BoundaryDetectionService
    if config.monitoring.strategy != "adaptive_stream":
        return StaticConformalDetectionService
    fitted_once = any(
        node.kind == "detector" and component_learning(node.component) == "batch"
        for node in nodes
    )
    return MixedDetectionService if fitted_once else AdaptiveStreamDetectionService
