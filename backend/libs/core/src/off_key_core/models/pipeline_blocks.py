"""Blocks: chains of steps a design copies in, kept outside any design."""

from collections.abc import Sequence

from ..schemas.pipelines import PipelineBlockStep
from .pipeline_catalog import pipeline_components


def require_block_steps(steps: Sequence[PipelineBlockStep]) -> None:
    """Accept only steps that take features and give features.

    A chain connects each step to the next. The input, a merge, a detector,
    the calibration step, the detection rule and the output have connections
    a chain cannot keep, so they stay with their design.
    """
    components = {item.id: item for item in pipeline_components()}
    for step in steps:
        component = components.get(step.component)
        if component is None or component.contract_version != step.contract_version:
            raise ValueError(f"{step.component} is not a step this version offers")
        if component.kind != "transform":
            raise ValueError(
                f"{component.label} cannot be part of a block. A block holds "
                "steps between the input and a detector."
            )
