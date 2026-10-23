"""Training-only batch preprocessing, frozen before conformal calibration."""

from __future__ import annotations

from collections import Counter
from time import perf_counter_ns

import numpy as np

from ..execution_errors import FatalExecutionError
from .components import BATCH_PASSTHROUGH, batch_component
from .plan import ExecutionPlan


class BatchFeatureGraph:
    """A fitted numerical graph owned by one static run.

    A training pass fits each shared component once. Calibration and scoring
    use transform only; a branch never receives another branch's writable array.
    Intermediate arrays are released after their final consumer.
    """

    def __init__(self, plan: ExecutionPlan):
        self.plan = plan
        self.components = {
            node.id: batch_component(node)
            for node in plan.feature_nodes
            if node.component not in BATCH_PASSTHROUGH
        }
        self.fitted = False

    def fit_transform(self, matrix: np.ndarray) -> np.ndarray:
        if self.fitted:
            raise RuntimeError("Static preprocessing is already frozen")
        transformed = self._execute(matrix, fit=True)
        self.fitted = True
        return transformed

    def transform(self, matrix: np.ndarray, observer=None) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("Static preprocessing has not been fitted")
        return self._execute(matrix, fit=False, observer=observer)

    def _execute(self, matrix: np.ndarray, *, fit: bool, observer=None) -> np.ndarray:
        source = self.plan.source_id
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.plan.names(source)):
            raise ValueError("Batch graph input width differs from its compiled schema")
        if not np.isfinite(matrix).all():
            raise ValueError("Batch graph requires finite inputs")
        available = {source: matrix}
        remaining = Counter(
            parent
            for node in self.plan.feature_nodes
            for parent in self.plan.parents(node.id)
        )
        output_id = self.plan.feature_output_id
        remaining[output_id] += 1
        for node in self.plan.feature_nodes:
            started = perf_counter_ns()
            parents = self.plan.parents(node.id)
            current = available[parents[0]]
            input_names = [
                name for parent in parents for name in self.plan.names(parent)
            ]
            result = self._execute_node(node, available, parents, input_names, fit)
            available[node.id] = result
            if observer is not None and len(matrix) == 1:
                inputs = result if node.kind == "merge" else current
                observer.record(
                    node.id,
                    dict(zip(input_names, inputs[0], strict=True)),
                    dict(zip(self.plan.names(node.id), result[0], strict=True)),
                    elapsed_ns=perf_counter_ns() - started,
                )
            for parent in parents:
                remaining[parent] -= 1
                if remaining[parent] == 0:
                    del available[parent]
        return available[output_id]

    def _execute_node(self, node, available, parents, names, fit):
        try:
            current = available[parents[0]]
            result = (
                np.concatenate([available[key] for key in parents], axis=1)
                if node.kind == "merge"
                else self._transform_node(node, current, names, fit)
            )
            result = np.asarray(result, dtype=float)
            if result.shape != (len(current), len(self.plan.names(node.id))):
                raise ValueError(f"Component {node.id} returned an incompatible matrix")
            if not np.isfinite(result).all():
                raise ValueError(f"Component {node.id} returned non-finite features")
            return result
        except Exception as error:
            raise FatalExecutionError(str(error), node_id=node.id) from error

    def _transform_node(self, node, current, names, fit):
        if node.component == "features.select":
            return current[:, [names.index(name) for name in node.params["features"]]]
        if node.component in {"features.rename", "features.passthrough"}:
            return current.copy()
        component = self.components[node.id]
        result = (
            component.fit_transform(current.copy())
            if fit
            else component.transform(current.copy())
        )
        return result.toarray() if hasattr(result, "toarray") else result


class FittedStaticPipeline:
    """One preprocessing/conformal inference; diagnostics never replay a model."""

    def __init__(self, graph: BatchFeatureGraph, conformal):
        self.graph = graph
        self.conformal = conformal
        self.observer = None
        self.last_features: dict[str, float] | None = None

    def __getstate__(self):
        return {**self.__dict__, "observer": None, "last_features": None}

    def compute_p_values(self, matrix):
        transformed = self.graph.transform(matrix, observer=self.observer)
        names = self.graph.plan.output_features
        self.last_features = (
            dict(zip(names, transformed[0], strict=True))
            if len(transformed) == 1
            else None
        )
        started = perf_counter_ns()
        result = self.conformal.compute_p_values(transformed)
        if self.observer is not None and len(transformed) == 1:
            self.observer.record(
                self.graph.plan.detector_id,
                self.last_features,
                float(np.asarray(result).ravel()[0]),
                elapsed_ns=perf_counter_ns() - started,
            )
        return result
