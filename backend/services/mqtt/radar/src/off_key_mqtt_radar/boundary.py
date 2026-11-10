"""A boundary on a run's scores that keeps adapting, and the rule on it.

A calibration method from ``aberrant.calibration`` issues the boundary for
each observation before its score is known, then learns the score. The
calibration window seeds it; from then on every scored observation updates
it, anomalous or not. The method holds the long-run share of scores above
the boundary at its alarm rate, so it also gets used to a lasting anomaly.

One detector's raw score is the method's score. Several detectors meet as
ranks against their own latest scores, combined into one surprise; a score
above all of its detector's latest ones counts for how far above it is.

The exceedance rule is separate from the boundary: it alarms once enough
scores in a row are above it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from aberrant.calibration import ScoreCalibrator
from off_key_core.models.pipeline_calibration import calibrator_id
from off_key_core.models.pipeline_parameters import fusion_mode

from .fusion import RollingRanks
from .pipelines.plan import ExecutionPlan


@dataclass(frozen=True)
class Judgement:
    """One observation against the boundary issued for it."""

    key: int
    scores: tuple[float, ...]
    # Each detector's surprise; none when one detector's raw score is judged.
    # Above 1 for a score beyond all of that detector's latest ones.
    surprises: tuple[float, ...] | None
    value: float
    threshold: float
    exceeded: bool
    alarm: bool


def adapts(plan: ExecutionPlan) -> bool:
    """Whether the design's calibration step keeps adapting."""
    identifier = plan.compiled.calibration_id
    return (
        identifier is not None
        and calibrator_id(plan.nodes[identifier].component) is not None
    )


class ScoreBoundary:
    """The calibration step and the exceedance rule of one run."""

    def __init__(self, plan: ExecutionPlan) -> None:
        identifier = plan.compiled.calibration_id
        method = (
            None
            if identifier is None
            else calibrator_id(plan.nodes[identifier].component)
        )
        if identifier is None or method is None:
            raise ValueError("The design has no calibration step that adapts")
        params = dict(plan.nodes[identifier].params)
        self.method = method
        self.alpha = float(params.pop("alpha"))
        self.fusion = fusion_mode(params)
        params.pop("fusion", None)
        self.params: dict[str, Any] = params
        self.window = plan.compiled.definition.settings.calibration_window_size
        self.consecutive = int(plan.nodes[plan.policy_id].params["consecutive"])
        self.detectors = len(plan.detector_ids)
        # Built now, so a setting the method refuses fails before any data.
        self.calibrator = self._calibrator()
        self.ranks: RollingRanks | None = None
        self.started = False
        self.key = 0
        # Scores above the boundary in a row, up to the current observation.
        self.run = 0

    @property
    def settings(self) -> dict[str, Any]:
        """What the design asks of this boundary; a checkpoint must match it."""
        return {
            "method": self.method,
            "alpha": self.alpha,
            "parameters": dict(self.params),
            "window": self.window,
            "fusion": self.fusion if self.detectors > 1 else None,
            "detectors": self.detectors,
            "consecutive": self.consecutive,
        }

    def _calibrator(self) -> ScoreCalibrator:
        return ScoreCalibrator(
            self.method, alpha=self.alpha, window=self.window, **self.params
        )

    def start(self, calibration: list[list[float]]) -> None:
        """Seed the boundary with the calibration window, one row per observation."""
        self.calibrator = self._calibrator()
        if self.detectors > 1:
            self.ranks = RollingRanks(calibration, self.fusion)
            values = self.ranks.seed
        else:
            self.ranks = None
            values = [float(row[0]) for row in calibration]
        for value in values:
            self._learn(value)
        self.run = 0
        self.started = True

    def _learn(self, value: float) -> None:
        self.calibrator.predict(self.key)
        self.calibrator.update(self.key, value)
        self.key += 1

    def judge(self, scores: list[float]) -> Judgement:
        """Compare an observation with its boundary; nothing is learned yet."""
        if not self.started:
            raise RuntimeError("The boundary has no calibration window yet")
        surprises = None
        if self.ranks is None:
            value = float(scores[0])
        else:
            surprises = tuple(self.ranks.surprises(scores))
            value = self.ranks.value(list(surprises))
        if not math.isfinite(value):
            raise ValueError("Detector scores must be finite")
        threshold = float(self.calibrator.predict(self.key))
        exceeded = value > threshold
        return Judgement(
            key=self.key,
            scores=tuple(float(score) for score in scores),
            surprises=surprises,
            value=value,
            threshold=threshold,
            exceeded=exceeded,
            alarm=exceeded and self.run + 1 >= self.consecutive,
        )

    def learn(self, judgement: Judgement) -> None:
        """Take a judged observation in: the method, the ranks and the run."""
        if judgement.key != self.key:
            raise RuntimeError("The boundary learns each observation once, in order")
        self.calibrator.update(self.key, judgement.value)
        self.key += 1
        if self.ranks is not None:
            self.ranks.push(list(judgement.scores))
        self.run = self.run + 1 if judgement.exceeded else 0

    def next_threshold(self) -> float:
        """The boundary the next observation meets."""
        return float(self.calibrator.predict(self.key))

    def spread(self) -> float:
        """The range of the latest window of scores, for an alarm's severity."""
        return float(self.calibrator.history.spread(self.window))
