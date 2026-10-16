"""Known graph allocations shared by startup admission and preflight."""

import sys
from collections import Counter

from pydantic import BaseModel

from .plan import ExecutionPlan


class ResourceEstimate(BaseModel):
    """Known numeric allocations; algorithm-internal allocations remain additional."""

    input_buffer_numeric_bytes: int
    input_buffer_container_bytes: int
    peak_intermediate_numeric_bytes: int
    projection_state_numeric_bytes: int
    known_numeric_bytes: int
    known_minimum_bytes: int
    memory_limit_mb: int
    description: str = (
        "Numeric matrices, initialization buffers and retained raw Python "
        "containers. Native workspaces and detector allocations require more memory; "
        "the worker hard limit remains authoritative."
    )


def estimate_resources(plan: ExecutionPlan, memory_limit_mb: int) -> ResourceEstimate:
    definition = plan.compiled.definition
    source = plan.compiled.source_id
    samples = (
        definition.settings.training_window_size
        + definition.settings.calibration_window_size
    )
    static = definition.strategy == "static_baseline"
    input_buffer = samples * len(plan.names(source)) * 8 if static else 0
    # Collection retains one dict and Python float per observation/feature until
    # the fitted result publishes. Keys are shared by the frozen source schema.
    # Training submission also keeps shallow list snapshots while fitting.
    row_bytes = sys.getsizeof(dict.fromkeys(plan.names(source), 0.0))
    row_bytes += len(plan.names(source)) * sys.getsizeof(0.0)
    containers = (samples * (row_bytes + 18) + 4 * sys.getsizeof([])) if static else 0
    remaining = Counter(
        parent for node in plan.feature_nodes for parent in plan.parents(node.id)
    )
    remaining[plan.compiled.feature_output_id] += 1
    alive = {source: len(plan.names(source))}
    peak = sum(alive.values())
    initialization = 0
    for node in plan.feature_nodes:
        alive[node.id] = len(plan.names(node.id))
        peak = max(peak, sum(alive.values()))
        width = len(plan.names(plan.parents(node.id)[0]))
        if node.component == "adaptive.uncentered_pca":
            initialization += (node.params["n0"] * width + width * width) * 8
        elif node.component in {
            "static.pca",
            "static.random_projection",
            "adaptive.random_projection",
        }:
            initialization += width * len(plan.names(node.id)) * 8
        for parent in plan.parents(node.id):
            remaining[parent] -= 1
            if remaining[parent] == 0:
                alive.pop(parent)
    # Fitting keeps transformed training and calibration matrices until model
    # calibration completes. Account for them in addition to branch traversal.
    intermediates = peak * (samples if static else 1) * 8
    known = input_buffer + intermediates + initialization
    if known + containers > memory_limit_mb * 1024 * 1024:
        raise ValueError(
            "Known pipeline numeric allocations exceed the worker memory limit"
        )
    return ResourceEstimate(
        input_buffer_numeric_bytes=input_buffer,
        input_buffer_container_bytes=containers,
        peak_intermediate_numeric_bytes=intermediates,
        projection_state_numeric_bytes=initialization,
        known_numeric_bytes=known,
        known_minimum_bytes=known + containers,
        memory_limit_mb=memory_limit_mb,
    )
