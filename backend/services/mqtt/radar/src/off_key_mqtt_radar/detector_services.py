"""The detector service that runs a monitor's design.

The policy picks the settings: the conformal alarm policy runs a static
baseline. A threshold run whose detectors all learn continuously is an
adaptive stream; one that also has detectors fitted once runs them side by
side, meeting at the fixed split.
"""

from off_key_core.schemas.pipeline_versions import component_learning

from .adaptive_detector import AdaptiveStreamDetectionService
from .detector import StaticConformalDetectionService
from .mixed_detector import MixedDetectionService


def detector_service_class(config):
    if config.monitoring.strategy != "adaptive_stream":
        return StaticConformalDetectionService
    fitted_once = any(
        node.kind == "detector" and component_learning(node.component) == "batch"
        for node in config.pipeline.definition.nodes
    )
    return MixedDetectionService if fitted_once else AdaptiveStreamDetectionService
