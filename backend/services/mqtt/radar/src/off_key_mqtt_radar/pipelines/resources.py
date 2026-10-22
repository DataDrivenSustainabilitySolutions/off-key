"""Known graph allocations shared by startup admission and preflight."""

import sys
from collections import Counter
from struct import calcsize

import numpy as np
from pydantic import BaseModel

from .plan import ExecutionPlan


class ResourceEstimate(BaseModel):
    """Known allocations; algorithm-internal allocations remain additional."""

    input_buffer_numeric_bytes: int
    input_buffer_container_bytes: int
    peak_intermediate_numeric_bytes: int
    projection_state_numeric_bytes: int
    projection_state_container_bytes: int
    known_numeric_bytes: int
    known_minimum_bytes: int
    memory_limit_mb: int
    description: str = (
        "Conservative known numeric matrices, initialization buffers, NumPy array "
        "headers and retained Python containers. Per-projection peaks are summed; "
        "native workspaces and detector allocations require additional memory. "
        "The worker hard limit remains authoritative."
    )


def _adaptive_pca_allocations(
    samples: int, width: int, components: int
) -> tuple[int, int]:
    """Model Aberrant's owning row arrays, transactional lists and reduced SVD.

    The transaction retains the previous window while initialization creates a
    new shallow list. The lists share their row arrays, so row data is counted
    once. Both pointer capacities include CPython's list overallocation margin.
    Array headers are measured in this target worker's NumPy/Python runtime.
    """
    rank = min(samples, width)
    row_values = samples * width
    # Initialization retains the rows, materializes a dense matrix and computes
    # reduced U/S/Vt. Normalizing S and publishing eigenvalues create new arrays;
    # the projected basis keeps the entire Vt allocation alive through views.
    initialization_values = (
        row_values + samples * width + samples * rank + 2 * rank + rank * width
    ) + components
    # Online updates can retain old/new bases and expand by one component. This
    # includes the explicit covariance/eigenvector matrices and working vectors;
    # LAPACK's implementation-specific native workspace remains additional.
    expanded = components + 1
    online_values = (
        3 * width * expanded + 4 * expanded * expanded + 3 * width + 8 * expanded
    )
    numeric = max(initialization_values, online_values) * np.dtype(float).itemsize
    list_capacity = samples + (samples + 7) // 8 + 6
    lists = 2 * (sys.getsizeof([]) + list_capacity * calcsize("P"))
    vector_header = sys.getsizeof(np.empty(0))
    matrix_header = sys.getsizeof(np.empty((0, 0)))
    # The small fixed allowance covers replaced states, decomposition results
    # and NumPy views in addition to the n0 independently owned row arrays.
    containers = lists + samples * vector_header + 10 * (vector_header + matrix_header)
    return numeric, containers


def estimate_resources(plan: ExecutionPlan, memory_limit_mb: int) -> ResourceEstimate:
    definition = plan.compiled.definition
    source = plan.source_id
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
    remaining[plan.feature_output_id] += 1
    alive = {source: len(plan.names(source))}
    peak = sum(alive.values())
    initialization = 0
    projection_containers = 0
    for node in plan.feature_nodes:
        alive[node.id] = len(plan.names(node.id))
        peak = max(peak, sum(alive.values()))
        width = len(plan.names(plan.parents(node.id)[0]))
        if node.component == "adaptive.uncentered_pca":
            numeric, retained = _adaptive_pca_allocations(
                node.params["n0"], width, len(plan.names(node.id))
            )
            initialization += numeric
            projection_containers += retained
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
    total = known + containers + projection_containers
    if total > memory_limit_mb * 1024 * 1024:
        raise ValueError("Known pipeline allocations exceed the worker memory limit")
    return ResourceEstimate(
        input_buffer_numeric_bytes=input_buffer,
        input_buffer_container_bytes=containers,
        peak_intermediate_numeric_bytes=intermediates,
        projection_state_numeric_bytes=initialization,
        projection_state_container_bytes=projection_containers,
        known_numeric_bytes=known,
        known_minimum_bytes=total,
        memory_limit_mb=memory_limit_mb,
    )
