"""What every forecasting model in the service provides."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

# Called with the fraction downloaded, in [0, 1].
Progress = Callable[[float], None]


@dataclass(frozen=True)
class ModelSpec:
    """Static facts about a model, known before anything is downloaded."""

    id: str
    family: str
    label: str
    licence: str
    levels: tuple[float, ...]
    max_context: int
    max_horizon: int
    parameters: int | None = None
    download_bytes: int = 0
    source: str | None = None
    revision: str | None = None


class LoadedModel(Protocol):
    def forecast(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        """Quantiles shaped ``(len(series), horizon, len(levels))``.

        Each series is float64, ends at the latest reading and may hold NaN for
        missing readings. Quantiles are non-decreasing along the last axis.
        """
        ...


class Provider(Protocol):
    spec: ModelSpec

    def is_downloaded(self, cache_dir: Path) -> bool:
        """Whether the weights are complete in the cache."""
        ...

    def download(self, cache_dir: Path, progress: Progress) -> None:
        """Fetch the weights into the cache; a no-op for models without weights."""
        ...

    def load(self, cache_dir: Path) -> LoadedModel:
        """Load downloaded weights for inference."""
        ...


def monotone(quantiles: np.ndarray) -> np.ndarray:
    """Sort along the level axis so no quantile crosses the next."""
    return np.sort(quantiles, axis=-1)
