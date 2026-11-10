"""Runs whose detectors learn in different ways.

Detectors fitted once buffer the training and calibration windows and fit
after them; detectors that learn continuously warm up, then score and learn
every observation. They meet at the fixed split: each detector's score is
ranked against its own calibration scores, the ranks are combined, and the
policy's quantile of the calibration observations' combined ranks is the
threshold. Results, checkpoints and health read as a threshold run's.
"""

from __future__ import annotations

import concurrent.futures
import logging
from collections import deque
from time import perf_counter_ns
from typing import Any

import numpy as np
from off_key_core.schemas.pipeline_versions import component_learning

from .adaptive_detector import AdaptiveStreamDetectionService, AdaptiveStreamState
from .config.config import AnomalyDetectionConfig
from .execution_errors import FatalExecutionError
from .models import AnomalyResult
from .pipelines.batch import BatchFeatureGraph, NonFiniteFeatures
from .pipelines.plan import ExecutionPlan
from .pipelines.pyod import calibrated_detector, node_detector

logger = logging.getLogger(__name__)


def learning_ids(plan: ExecutionPlan, mode: str) -> list[str]:
    """The detectors that learn this way, in the run's order."""
    return [
        identifier
        for identifier in plan.detector_ids
        if component_learning(plan.nodes[identifier].component) == mode
    ]


def fit_batch_branches(
    plan: ExecutionPlan,
    detector_ids: list[str],
    training: list[list[float]],
    calibration: list[list[float]],
    seed: int | None,
):
    """Fit the steps and detectors that learn once; give their calibration scores."""
    graph = BatchFeatureGraph(plan, detector_ids)
    trained = graph.fit_transform_all(np.asarray(training, dtype=float))
    calibrated = graph.transform_all(np.asarray(calibration, dtype=float))
    detectors, columns = {}, {}
    for identifier in detector_ids:
        source = plan.detector_inputs[identifier]
        try:
            detector = calibrated_detector(
                node_detector(plan.nodes[identifier], seed),
                trained[source],
                calibrated[source],
                seed,
            )
            scores = np.asarray(detector.calibration_set, dtype=float).reshape(-1)
        except Exception as error:
            raise FatalExecutionError(str(error), node_id=identifier) from error
        if scores.shape != (len(calibration),) or not np.isfinite(scores).all():
            raise FatalExecutionError(
                f"Detector {identifier} gave no finite score for every "
                "calibration observation",
                node_id=identifier,
            )
        detectors[identifier] = detector
        columns[identifier] = scores
    return graph, detectors, columns


class BatchBranches:
    """The detectors fitted once, the steps they read, and their buffers."""

    def __init__(
        self,
        plan: ExecutionPlan,
        detector_ids: list[str],
        training_size: int,
    ) -> None:
        self.plan = plan
        self.detector_ids = list(detector_ids)
        # If the online detectors need longer to warm up, the latest window
        # is what the others fit on.
        self.training: deque[list[float]] = deque(maxlen=training_size)
        self.calibration: list[list[float]] = []
        self.graph: BatchFeatureGraph | None = None
        self.detectors: dict[str, Any] | None = None
        self.last_features: dict[str, dict[str, float]] = {}

    def __getstate__(self):
        return {**self.__dict__, "last_features": {}}

    @property
    def fitted(self) -> bool:
        return self.detectors is not None

    def vector(self, data: dict[str, float]) -> list[float]:
        return [float(data[key]) for key in self.plan.input_columns]

    def publish(self, graph: BatchFeatureGraph, detectors: dict[str, Any]) -> None:
        self.graph, self.detectors = graph, detectors
        self.training.clear()
        self.calibration = []

    def scores(self, data: dict[str, float], observer=None) -> dict[str, float]:
        """Each frozen detector's score; scoring only reads fitted state."""
        if self.graph is None or self.detectors is None:
            raise RuntimeError("Detectors fitted once have not been fitted")
        matrix = np.asarray([self.vector(data)], dtype=float)
        outputs = self.graph.transform_all(matrix, observer=observer)
        scores, features = {}, {}
        for identifier, detector in self.detectors.items():
            row = outputs[self.plan.detector_inputs[identifier]]
            features[identifier] = dict(
                zip(self.plan.detector_features(identifier), row[0], strict=True)
            )
            started = perf_counter_ns()
            score = float(np.asarray(detector.score_samples(row), dtype=float)[0])
            if not np.isfinite(score):
                raise NonFiniteFeatures(
                    f"Detector {identifier} returned a non-finite score",
                    node_id=identifier,
                )
            if observer is not None:
                observer.record(
                    identifier,
                    features[identifier],
                    score,
                    elapsed_ns=perf_counter_ns() - started,
                )
            scores[identifier] = score
        self.last_features = features
        return scores


class MixedDetectionService(AdaptiveStreamDetectionService):
    """Detectors fitted once beside detectors that learn every observation."""

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self._fit_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._fit_future: concurrent.futures.Future | None = None
        super().__init__(config, checkpoint)

    @staticmethod
    def _runs(plan) -> bool:
        return bool(learning_ids(plan, "batch")) and bool(learning_ids(plan, "online"))

    def _online_ids(self) -> list[str]:
        return learning_ids(self.plan, "online")

    def _initialize_fresh(self) -> None:
        super()._initialize_fresh()
        self.batch = BatchBranches(
            self.plan,
            learning_ids(self.plan, "batch"),
            self.adaptive_config.training_window_size,
        )

    def _restore(self, checkpoint: dict[str, Any]) -> None:
        batch = checkpoint.get("batch")
        if not isinstance(batch, BatchBranches) or batch.detector_ids != (
            learning_ids(self.plan, "batch")
        ):
            raise ValueError("Checkpoint is missing the detectors fitted once")
        self.batch = batch
        state = AdaptiveStreamState(checkpoint["adaptive_state"])
        if state == AdaptiveStreamState.OPERATIONAL and not batch.fitted:
            raise ValueError("Operational checkpoint has unfitted detectors")
        super()._restore(checkpoint)
        if self.state == AdaptiveStreamState.FITTING:
            self._submit_fit()

    def export_checkpoint(self) -> dict[str, Any]:
        checkpoint = super().export_checkpoint()
        checkpoint["batch"] = self.batch
        return checkpoint

    def _process_warmup(self, data, topic, charger_id, started) -> AnomalyResult:
        result = super()._process_warmup(data, topic, charger_id, started)
        self.batch.training.append(self.batch.vector(data))
        return result

    def _process_current_state(self, data, topic, charger_id, started):
        self._publish_fit()
        if self.state == AdaptiveStreamState.FITTING:
            # The online detectors keep learning while the others fit.
            self._learn(data)
            self.processed_count += 1
            return self._result(data, 0.0, False, "fitting", topic, charger_id, started)
        return super()._process_current_state(data, topic, charger_id, started)

    def _calibrate_fused(self, data, topic, charger_id, started) -> AnomalyResult:
        """Online detectors score and learn; the others keep the observation."""
        scores = self._scores(data)
        self._learn(data)
        self.batch.calibration.append(self.batch.vector(data))
        self.calibration_scores.append(scores)
        self.calibration_count += 1
        self.processed_count += 1
        self._detector_results = [
            {"detector_id": identifier, "score": score, "surprise": None}
            for identifier, score in zip(self.online_ids, scores, strict=True)
        ]
        if self.calibration_count >= self.adaptive_config.calibration_window_size:
            self.state = AdaptiveStreamState.FITTING
            self._submit_fit()
            self.logger.info(
                "event=radar.mixed_fitting_started calibration_count=%s",
                self.calibration_count,
            )
        return self._result(data, 0.0, False, "calibration", topic, charger_id, started)

    def _fused_scores(self, data: dict[str, float]) -> list[float]:
        online = dict(zip(self.online_ids, self._scores(data), strict=True))
        try:
            fitted = self.batch.scores(data, self.diagnostics)
        except NonFiniteFeatures as error:
            # Scoring only read fitted state, so the observation is skipped.
            self._skip(
                error.node_id or self.batch.detector_ids[0], "non_finite", str(error)
            )
        self._scored_features = {
            **(self._scored_features or {}),
            **self.batch.last_features,
        }
        return [
            online[identifier] if identifier in online else fitted[identifier]
            for identifier in self.plan.detector_ids
        ]

    def _submit_fit(self) -> None:
        if self._fit_executor is None:
            self._fit_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._fit_future = self._fit_executor.submit(
            fit_batch_branches,
            self.plan,
            list(self.batch.detector_ids),
            list(self.batch.training),
            list(self.batch.calibration),
            self.plan.compiled.definition.settings.seed,
        )

    def _publish_fit(self) -> None:
        """Freeze the threshold once the detectors that learn once are fitted."""
        future = self._fit_future
        if (
            self.state != AdaptiveStreamState.FITTING
            or future is None
            or not future.done()
        ):
            return
        self._fit_future = None
        try:
            graph, detectors, columns = future.result()
        except Exception as error:
            self._execution_failed = True
            self.state = AdaptiveStreamState.FAILED
            self.training_error = str(error)
            identifier = self._failure_node(error, self.batch.detector_ids[0])
            self._diagnose(self.diagnostics.fail, identifier, error)
            raise FatalExecutionError(str(error), node_id=identifier) from error
        online = {
            identifier: [row[index] for row in self.calibration_scores]
            for index, identifier in enumerate(self.online_ids)
        }
        self.calibration_scores = [
            [
                float(online[identifier][row])
                if identifier in online
                else float(columns[identifier][row])
                for identifier in self.plan.detector_ids
            ]
            for row in range(self.calibration_count)
        ]
        self.batch.publish(graph, detectors)
        self._freeze_fusion()
        self.state = AdaptiveStreamState.OPERATIONAL
        self._diagnose(self._publish_fit_readiness)
        self._log_calibrated()

    def _publish_fit_readiness(self) -> None:
        if self.batch.graph is None:
            return
        for node in self.batch.graph.nodes:
            self.diagnostics.nodes[node.id].update(state="ready", ready=True)
        for identifier in self.batch.detector_ids:
            self.diagnostics.nodes[identifier].update(state="ready", ready=True)

    def refresh_background_state(self) -> None:
        """Publish a finished fit without waiting for the next observation."""
        self._publish_fit()

    def wait_for_background(self) -> None:
        """Block until the fit ends, so a replay discards no observation."""
        future = self._fit_future
        if future is not None:
            concurrent.futures.wait([future])

    def shutdown(self) -> None:
        if self._fit_future is not None and not self._fit_future.done():
            self._fit_future.cancel()
        if self._fit_executor is not None:
            self._fit_executor.shutdown(wait=False, cancel_futures=True)

    def get_pipeline_state(self) -> dict[str, Any]:
        state = super().get_pipeline_state()
        state["batch_training"] = {
            "state": self.state.value,
            "training_samples": len(self.batch.training),
            "calibration_samples": len(self.batch.calibration),
            "frozen": self.batch.fitted,
        }
        return state
