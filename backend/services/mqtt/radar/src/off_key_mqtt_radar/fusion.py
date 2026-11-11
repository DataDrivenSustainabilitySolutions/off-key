"""Several detectors' scores as one value, by rank against calibration scores.

A score's surprise is the share of its detector's calibration scores below it,
so detectors with different scales combine without tuning. Combining takes the
largest surprise (max) or the mean. Counts stay integers, so ties are exact.
"""

from __future__ import annotations

import bisect
from collections import deque
from typing import Any

import numpy as np


class RankFusion:
    """Frozen calibration scores of every detector, one column per detector."""

    def __init__(self, calibration: Any, fusion: str):
        scores = np.asarray(calibration, dtype=float)
        if scores.ndim != 2 or scores.shape[0] < 1 or scores.shape[1] < 2:
            raise ValueError("Combining needs calibration scores of two detectors")
        if not np.isfinite(scores).all():
            raise ValueError("Calibration scores must be finite")
        if fusion not in {"max", "mean"}:
            raise ValueError(f"Unknown way to combine detectors: {fusion!r}")
        self.fusion = fusion
        self.calibration = scores
        self.sorted = np.sort(scores, axis=0)
        # How many of its detector's calibration scores lie below each one.
        self.below = np.column_stack(
            [
                np.searchsorted(self.sorted[:, column], scores[:, column], "left")
                for column in range(scores.shape[1])
            ]
        )

    @property
    def size(self) -> int:
        """The calibration observations, n."""
        return int(self.calibration.shape[0])

    @property
    def detectors(self) -> int:
        return int(self.calibration.shape[1])

    def counts(self, scores: Any) -> np.ndarray:
        """For each detector, its calibration scores below the new score."""
        values = self._scores(scores)
        return np.asarray(
            [
                np.searchsorted(self.sorted[:, column], value, "left")
                for column, value in enumerate(values)
            ],
            dtype=np.int64,
        )

    def surprises(self, scores: Any) -> list[float]:
        """Each detector's surprise: the share of its calibration scores below."""
        return [int(count) / self.size for count in self.counts(scores)]

    def combined(self, counts: np.ndarray) -> np.ndarray | int:
        """The combined count: the largest, or the sum for the mean."""
        if self.fusion == "max":
            return counts.max(axis=-1)
        return counts.sum(axis=-1)

    def value(self, combined: Any) -> float:
        """A combined count as the fused surprise between 0 and 1."""
        scale = self.size if self.fusion == "max" else self.size * self.detectors
        return float(combined) / scale

    def calibration_counts(self) -> np.ndarray:
        """Every calibration observation's combined count, against the others."""
        return np.asarray(self.combined(self.below), dtype=np.int64)

    def p_value(self, scores: Any, rng: np.random.Generator) -> float:
        """A conformal p-value for the new observation's combined surprise.

        The new observation and the calibration observations are ranked
        together: each calibration observation has one more score below it on
        every detector whose new score is lower. Their combined counts are then
        exchangeable without a change, so the new observation's rank among the
        n + 1, with ties broken at random, is uniform on 1 to n + 1. The
        p-value is that rank over n + 1, as one detector's p-values are.
        """
        values = self._scores(scores)
        test = int(self.combined(self.counts(values)))
        rows = self.combined(self.below + (values < self.calibration))
        greater = int(np.count_nonzero(rows > test))
        ties = int(np.count_nonzero(rows == test))
        rank = greater + 1 + int(rng.integers(0, ties + 1))
        return rank / (self.size + 1)

    def _scores(self, scores: Any) -> np.ndarray:
        values = np.asarray(scores, dtype=float).reshape(-1)
        if values.shape != (self.detectors,):
            raise ValueError(
                f"Expected {self.detectors} detector scores; got {values.size}"
            )
        if not np.isfinite(values).all():
            raise ValueError("Detector scores must be finite")
        return values


def threshold_count(fusion: RankFusion, quantile: float) -> int:
    """The policy's quantile of the calibration observations' combined counts."""
    return int(np.quantile(fusion.calibration_counts(), quantile, method="higher"))


class RollingRanks:
    """Each detector's latest scores, for a boundary that keeps adapting.

    A fixed split ranks every later score against the frozen calibration
    scores. A boundary that adapts follows its detectors instead: each new
    score is ranked against that detector's last n scores, n being the
    calibration window, and then joins them. The combined surprise is one
    value, which the calibration method sees as its score.

    A share alone stops at 1: a score just above the window and one far above
    it would tie, and a boundary that has reached 1 could never be exceeded.
    So a score above its whole window adds how far above, in units of the
    window's range.
    """

    def __init__(self, calibration: Any, fusion: str):
        frozen = RankFusion(calibration, fusion)
        self.fusion = fusion
        self.size = frozen.size
        self.detectors = frozen.detectors
        columns = frozen.calibration.T.tolist()
        self.windows = [deque(column, maxlen=self.size) for column in columns]
        self.sorted = [sorted(column) for column in columns]
        # Each calibration observation, ranked within the calibration window.
        self.seed = [
            frozen.value(count) for count in frozen.calibration_counts().tolist()
        ]

    def surprises(self, scores: list[float]) -> list[float]:
        """Each detector's surprise: the share of its latest scores below the
        new one, plus the distance above them all in units of their range."""
        if len(scores) != self.detectors:
            raise ValueError(
                f"Expected {self.detectors} detector scores; got {len(scores)}"
            )
        surprises = []
        for ordered, score in zip(self.sorted, scores, strict=True):
            surprise = bisect.bisect_left(ordered, score) / self.size
            if score > ordered[-1]:
                # A window of equal scores has no range; its level stands in.
                scale = ordered[-1] - ordered[0] or abs(ordered[-1]) or 1.0
                surprise += (score - ordered[-1]) / scale
            surprises.append(surprise)
        return surprises

    def value(self, surprises: list[float]) -> float:
        """The combined surprise: the largest, or their mean."""
        if self.fusion == "max":
            return max(surprises)
        return sum(surprises) / self.detectors

    def push(self, scores: list[float]) -> None:
        """Each detector's oldest score leaves its window and the new one joins."""
        for window, ordered, score in zip(
            self.windows, self.sorted, scores, strict=True
        ):
            del ordered[bisect.bisect_left(ordered, window[0])]
            window.append(score)
            bisect.insort_left(ordered, score)
