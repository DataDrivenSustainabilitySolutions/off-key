"""Seasonal-naive forecasts with empirical quantiles: no weights, always ready.

It repeats the last observed season and widens the band with the spread of the
series' own seasonal differences. It is the baseline any pretrained model has
to beat, and it lets the whole service path run without downloads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from off_key_core.schemas.forecast import (
    MAX_CONTEXT_LENGTH,
    MAX_HORIZON,
    QUANTILE_LEVELS,
)

from .base import ModelSpec, Progress, monotone


@dataclass(frozen=True)
class SeasonalNaive:
    season_length: int
    levels: tuple[float, ...] = QUANTILE_LEVELS

    def forecast(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        return np.stack([self._one(values, horizon) for values in series])

    def _one(self, values: np.ndarray, horizon: int) -> np.ndarray:
        values = _filled(values)
        m = min(self.season_length, len(values))
        last_season = values[-m:]
        steps = np.arange(horizon)
        point = last_season[steps % m]
        # Seasons ahead of the latest one, so uncertainty grows like a random walk.
        seasons_ahead = steps // m + 1
        offsets = _difference_quantiles(values, m, self.levels)
        return monotone(point[:, None] + np.sqrt(seasons_ahead)[:, None] * offsets)


def _filled(values: np.ndarray) -> np.ndarray:
    """Carry the last reading forward over gaps, and back over leading gaps."""
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    index = np.where(finite, np.arange(len(values)), 0)
    np.maximum.accumulate(index, out=index)
    filled = values[index]
    first = int(np.argmax(finite))
    filled[:first] = values[first]
    return filled


def _difference_quantiles(
    values: np.ndarray, lag: int, levels: tuple[float, ...]
) -> np.ndarray:
    differences = values[lag:] - values[:-lag]
    if len(differences) < 2:
        return np.zeros(len(levels))
    centred = differences - np.median(differences)
    return np.quantile(centred, levels)


class SeasonalNaiveProvider:
    """One model per season length; the length is part of the model id."""

    def __init__(self, season_length: int) -> None:
        if season_length < 1:
            raise ValueError("season_length must be at least 1")
        self.season_length = season_length
        label = (
            "Naive (last value)"
            if season_length == 1
            else f"Seasonal naive, season {season_length}"
        )
        self.spec = ModelSpec(
            id=f"naive/season-{season_length}",
            family="naive",
            label=label,
            licence="MIT (built in)",
            levels=QUANTILE_LEVELS,
            max_context=MAX_CONTEXT_LENGTH,
            max_horizon=MAX_HORIZON,
        )

    def is_downloaded(self, cache_dir: Path) -> bool:
        return True

    def download(self, cache_dir: Path, progress: Progress) -> None:
        progress(1.0)

    def load(self, cache_dir: Path) -> SeasonalNaive:
        return SeasonalNaive(self.season_length)


def naive_providers(season_lengths: Sequence[int]) -> list[SeasonalNaiveProvider]:
    return [SeasonalNaiveProvider(length) for length in sorted(set(season_lengths))]
