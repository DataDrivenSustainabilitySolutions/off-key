"""Other calibration methods, tried on the scores of a run as it happens.

A Dojo replay can ask what its design would have alarmed on with a different
calibration step. Each method here gets the calibration window and then every
detector score of the run, exactly as the run's own step does, and keeps its
own boundary and its own count of exceedances in a row. Nothing a method
decides reaches the run: it only marks which methods would have alarmed on
each observation.

All methods run at one alarm rate with their default settings, so the
comparison shows the method, not its tuning. Several detectors meet as they do
in a run: as ranks against their latest scores for a method that adapts, and
against their calibration scores for the fixed split.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence

import numpy as np
from aberrant.calibration import ScoreCalibrator
from off_key_core.models.dojo_runs import FIXED_METHOD

from .fusion import RankFusion, RollingRanks, threshold_count
from .pipelines.plan import ExecutionPlan

logger = logging.getLogger(__name__)


class _Frozen:
    """The fixed split: a threshold from the calibration window, never moved.

    One detector's threshold is a quantile of its calibration scores. Several
    detectors are ranked against their calibration scores for good, as a run
    with a fixed split ranks them.
    """

    def __init__(self, alpha: float, fusion: str) -> None:
        self.quantile = 1 - alpha
        self.fusion = fusion
        self.ranks: RankFusion | None = None
        self.threshold = math.inf

    def seed(self, rows: list[list[float]], values: list[float]) -> None:
        if len(rows[0]) > 1:
            self.ranks = RankFusion(rows, self.fusion)
            self.threshold = threshold_count(self.ranks, self.quantile)
        else:
            self.threshold = float(
                np.quantile(
                    np.asarray(rows, dtype=float), self.quantile, method="higher"
                )
            )

    def exceeded(self, scores: list[float], value: float) -> bool:
        if self.ranks is None:
            return scores[0] > self.threshold
        return int(self.ranks.combined(self.ranks.counts(scores))) > self.threshold


class _Adapting:
    """A method of ``aberrant.calibration``: predict, compare, then learn."""

    def __init__(self, method: str, alpha: float, window: int) -> None:
        self.calibrator = ScoreCalibrator(method, alpha=alpha, window=window)
        self.key = 0

    def seed(self, rows: list[list[float]], values: list[float]) -> None:
        for value in values:
            self.exceeded([], value)

    def exceeded(self, scores: list[float], value: float) -> bool:
        threshold = float(self.calibrator.predict(self.key))
        if math.isnan(threshold):
            raise ValueError("The method gave no boundary")
        self.calibrator.update(self.key, value)
        self.key += 1
        return value > threshold


class CalibrationComparison:
    """Which of `methods` would alarm on each observation of one run."""

    def __init__(
        self,
        plan: ExecutionPlan,
        methods: Sequence[str],
        *,
        alpha: float,
        consecutive: int,
    ) -> None:
        if len(methods) > 62:
            raise ValueError("At most 62 methods fit in one comparison")
        window = plan.compiled.definition.settings.calibration_window_size
        self.methods = list(methods)
        self.consecutive = int(consecutive)
        self.detectors = len(plan.detector_ids)
        self.fusion = plan.fusion
        self._boundaries: list[_Frozen | _Adapting | None] = [
            _Frozen(alpha, self.fusion)
            if method == FIXED_METHOD
            else _Adapting(method, alpha, window)
            for method in self.methods
        ]
        self._runs = [0] * len(self.methods)
        self._ranks: RollingRanks | None = None
        self.started = False
        # Why a method left the comparison, by method.
        self.failed: dict[str, str] = {}

    def start(self, calibration: Sequence[Sequence[float]]) -> None:
        """Seed every method with the calibration window, one row per observation."""
        rows = [[float(score) for score in row] for row in calibration]
        if self.detectors > 1:
            self._ranks = RollingRanks(rows, self.fusion)
            values = list(self._ranks.seed)
        else:
            values = [row[0] for row in rows]
        for index in range(len(self.methods)):
            self._guarded(index, lambda boundary: boundary.seed(rows, values))
        self.started = True

    def observe(self, scores: Sequence[float]) -> int:
        """One bit per method, set where it would alarm on these detector scores."""
        if not self.started:
            raise RuntimeError("The comparison has no calibration window yet")
        scores = [float(score) for score in scores]
        if self._ranks is None:
            value = scores[0]
        else:
            value = self._ranks.value(self._ranks.surprises(scores))
        alarms = 0
        for index in range(len(self.methods)):
            exceeded = self._guarded(
                index, lambda boundary: boundary.exceeded(scores, value)
            )
            self._runs[index] = self._runs[index] + 1 if exceeded else 0
            if self._runs[index] >= self.consecutive:
                alarms |= 1 << index
        if self._ranks is not None:
            self._ranks.push(scores)
        return alarms

    def _guarded(self, index: int, step) -> bool:
        """Run one method's step. A method that fails leaves the comparison;
        the run it shadows carries on."""
        boundary = self._boundaries[index]
        if boundary is None:
            return False
        try:
            return bool(step(boundary))
        except Exception as error:
            method = self.methods[index]
            self._boundaries[index] = None
            self.failed[method] = f"{type(error).__name__}: {error}"[:500]
            logger.warning(
                "event=radar.calibration_comparison_failed method=%s error=%s",
                method,
                error,
            )
            return False
