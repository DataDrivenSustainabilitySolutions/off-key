"""Known graph allocations shared by startup admission and preflight."""

import sys
from array import array
from collections import Counter
from collections.abc import Callable
from struct import calcsize
from typing import Any

import numpy as np
from off_key_core.models.pipeline_calibration import calibrator_id
from off_key_core.models.pipeline_prepare import LANE_COMPONENTS, kernel
from off_key_core.models.pipeline_scope import step_scope
from off_key_core.schemas.pipeline_versions import component_learning
from pydantic import BaseModel

from .plan import ExecutionPlan


class ResourceEstimate(BaseModel):
    """Known allocations; algorithm-internal allocations remain additional."""

    input_buffer_numeric_bytes: int
    input_buffer_container_bytes: int
    peak_intermediate_numeric_bytes: int
    projection_state_numeric_bytes: int
    projection_state_container_bytes: int
    prepare_state_bytes: int = 0
    fusion_state_bytes: int = 0
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


def _dense_projection(_node, width: int, outputs: int) -> tuple[int, int]:
    return width * outputs * 8, 0


def _rolling_windows(node, width: int, _outputs: int) -> tuple[int, int]:
    """Aberrant keeps one tuple of Python floats per feature and window.

    A learning transaction keeps the previous tuple while the next one and its
    sorted copy exist, so three pointer arrays per feature can be alive.
    """
    window = node.params["window_size"]
    floats = width * window * sys.getsizeof(0.0)
    pointers = width * 3 * (sys.getsizeof(()) + window * calcsize("P"))
    return floats, pointers


def _least_squares(_node, width: int, _outputs: int) -> tuple[int, int]:
    """At most a weight and a centre per feature the step uses."""
    return 2 * width * 8, 0


def _recursive_least_squares(_node, width: int, _outputs: int) -> tuple[int, int]:
    """The covariance of the coefficients, a square matrix of doubles.

    The fit holds one coefficient per feature the target is expected from and
    a constant, as many as the features the step uses. An update builds the
    next covariance from a handful of matrices of that size while the learning
    transaction holds a copy of the fit, so up to eight are alive at once.
    """
    return 8 * width * width * 8, 0


# Learned state as (numeric bytes, retained container bytes) per component.
STATE_ESTIMATORS: dict[str, Callable[[Any, int, int], tuple[int, int]]] = {
    "adaptive.uncentered_pca": lambda node, width, outputs: _adaptive_pca_allocations(
        node.params["n0"], width, outputs
    ),
    "static.pca": _dense_projection,
    "static.random_projection": _dense_projection,
    "adaptive.random_projection": _dense_projection,
    "adaptive.robust_scaler": _rolling_windows,
    "static.expected_value": _least_squares,
    "adaptive.expected_value": _recursive_least_squares,
}


def _prepare_state(plan: ExecutionPlan) -> int:
    """Each feature of a Prepare step keeps its window as an array of doubles.

    A step that needs order statistics keeps a sorted copy as well. A pass
    stages new arrays before the old ones are released, so twice the arrays can
    be alive at once. A rolling slope also keeps one array of window positions
    for the step. Row operations keep no state.
    """
    if plan.stage is None:
        return 0
    header = sys.getsizeof(array("d"))
    total = 0
    for identifier in plan.stage.steps:
        node = plan.nodes[identifier]
        if node.component not in LANE_COMPONENTS:
            continue
        step = kernel(node.component, node.params)
        initial = step.initial()
        arrays = sum(isinstance(item, array) for item in initial)
        lane = sys.getsizeof(initial) + arrays * (header + 8 * step.window)
        lane += sum(
            sys.getsizeof(item) for item in initial if not isinstance(item, array)
        )
        if node.component == "prepare.rolling" and node.params["statistic"] == "slope":
            total += header + 8 * step.window
        scope = step_scope(
            node.component, node.params, plan.names(plan.parents(identifier)[0])
        )
        total += 2 * len(scope.selected) * lane
    return total


def _fusion_state(plan: ExecutionPlan) -> int:
    """Combining detectors keeps every calibration score three times over.

    The rank fusion holds the scores, a sorted copy and the count below each
    one, eight bytes apiece; a scoring pass makes two more such matrices. An
    adaptive run first collects the scores as Python lists of floats.
    """
    if not plan.fused:
        return 0
    rows = plan.compiled.definition.settings.calibration_window_size
    width = len(plan.detector_ids)
    numeric = 5 * rows * width * 8
    if plan.compiled.definition.lane != "static_baseline":
        row = sys.getsizeof([0.0] * width) + width * sys.getsizeof(0.0)
        numeric += rows * (row + calcsize("P")) + sys.getsizeof([])
    return numeric


def _boundary_state(plan: ExecutionPlan) -> int:
    """A calibration step that adapts keeps its latest scores as Python floats.

    It collects the calibration window as lists of floats, then holds that
    window sorted and the latest scores in arrival order. Several detectors
    each keep their window twice, in arrival order and sorted. The method's
    own state is bounded by the largest one, 5,000 weighted scores.
    """
    identifier = plan.compiled.calibration_id
    if identifier is None or calibrator_id(plan.nodes[identifier].component) is None:
        return 0
    rows = plan.compiled.definition.settings.calibration_window_size
    width = len(plan.detector_ids)
    score = sys.getsizeof(0.0) + calcsize("P")
    collected = rows * (sys.getsizeof([0.0] * width) + width * score)
    history = (rows + max(rows, 1024)) * score
    ranks = 2 * rows * width * score if plan.fused else 0
    method = 5000 * (sys.getsizeof((0.0, 0)) + sys.getsizeof(0) + score)
    return collected + history + ranks + method


def estimate_resources(plan: ExecutionPlan, memory_limit_mb: int) -> ResourceEstimate:
    definition = plan.compiled.definition
    source = plan.source_id
    samples = (
        definition.settings.training_window_size
        + definition.settings.calibration_window_size
    )
    # A static baseline fits everything once. Detectors that learn in
    # different ways fit some once and copy the steps of the others.
    static = definition.lane == "static_baseline"
    online = [
        identifier
        for identifier in plan.detector_ids
        if component_learning(plan.nodes[identifier].component) != "batch"
    ]
    buffered = static or len(online) < len(plan.detector_ids)
    fitted_once = frozenset().union(
        *(
            plan.reads(identifier)
            for identifier in plan.detector_ids
            if identifier not in online
        )
    )
    # Static baselines buffer what the learned stage reads: the readings, or
    # the prepared columns when the design has a Prepare stage.
    columns = plan.input_columns
    input_buffer = samples * len(columns) * 8 if buffered else 0
    # Collection retains one dict and Python float per observation/feature until
    # the fitted result publishes. Keys are shared by the frozen source schema.
    # Training submission also keeps shallow list snapshots while fitting.
    row_bytes = sys.getsizeof(dict.fromkeys(columns, 0.0))
    row_bytes += len(columns) * sys.getsizeof(0.0)
    containers = (samples * (row_bytes + 18) + 4 * sys.getsizeof([])) if buffered else 0
    remaining = Counter(
        parent for node in plan.learned_nodes for parent in plan.parents(node.id)
    )
    remaining.update(dict.fromkeys(plan.detector_inputs.values(), 1))
    # Adaptive detectors each learn their own copy of the steps they read.
    copies = Counter(
        identifier
        for detector in online
        for identifier in (plan.reads(detector) if plan.fused else ())
    )
    alive = (
        {source: len(plan.names(source))}
        if plan.stage is None
        else {key: len(plan.names(key)) for key in plan.stage.frontier}
    )
    peak = sum(alive.values())
    initialization = 0
    projection_containers = 0
    prepare_state = _prepare_state(plan)
    for node in plan.learned_nodes:
        alive[node.id] = len(plan.names(node.id))
        peak = max(peak, sum(alive.values()))
        estimate = STATE_ESTIMATORS.get(node.component)
        if estimate is not None:
            # A scoped step holds state only for the features it uses.
            scope = step_scope(
                node.component, node.params, plan.names(plan.parents(node.id)[0])
            )
            outputs = node.params.get("n_components", len(scope.selected))
            numeric, retained = estimate(node, len(scope.selected), outputs)
            # A static run fits each step once; adaptive detectors keep a copy each.
            times = 1 if static else max(copies[node.id] + (node.id in fitted_once), 1)
            initialization += times * numeric
            projection_containers += times * retained
        for parent in plan.parents(node.id):
            remaining[parent] -= 1
            if remaining[parent] == 0:
                alive.pop(parent)
    # Fitting keeps transformed training and calibration matrices until model
    # calibration completes. Account for them in addition to branch traversal.
    intermediates = peak * (samples if buffered else 1) * 8
    fusion_state = _fusion_state(plan) + _boundary_state(plan)
    known = input_buffer + intermediates + initialization + fusion_state
    total = known + containers + projection_containers + prepare_state
    if total > memory_limit_mb * 1024 * 1024:
        raise ValueError("Known pipeline allocations exceed the worker memory limit")
    return ResourceEstimate(
        input_buffer_numeric_bytes=input_buffer,
        input_buffer_container_bytes=containers,
        peak_intermediate_numeric_bytes=intermediates,
        projection_state_numeric_bytes=initialization,
        projection_state_container_bytes=projection_containers,
        prepare_state_bytes=prepare_state,
        fusion_state_bytes=fusion_state,
        known_numeric_bytes=known,
        known_minimum_bytes=total,
        memory_limit_mb=memory_limit_mb,
    )
