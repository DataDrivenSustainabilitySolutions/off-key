"""Mistral's Timestral checkpoints, downloaded from the Hugging Face Hub on first use.

Weights: Mistral AI, Modified MIT (no rights above $20M global monthly revenue).
Code: the official ``timestral`` package, Apache 2.0. Both ``timestral`` and
``torch`` are optional dependencies of the service, so this provider is offered
only where they are installed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from off_key_core.schemas.forecast import (
    MAX_CONTEXT_LENGTH,
    MAX_HORIZON,
    QUANTILE_LEVELS,
)

from .base import ModelSpec, Progress, monotone

LICENCE = "Mistral AI Modified MIT (weights), Apache 2.0 (code)"
FILES = ("config.json", "model.safetensors")

# Parameters and fp32 weight sizes as published with the checkpoints.
CHECKPOINTS: dict[str, tuple[int, int]] = {
    "mistralai/Timestral-5M": (5_000_000, 21_000_000),
    "mistralai/Timestral-28M": (28_000_000, 111_000_000),
    "mistralai/Timestral-123M": (123_000_000, 490_000_000),
    "mistralai/Timestral-209M": (209_000_000, 837_000_000),
}


def timestral_installed() -> bool:
    return (
        importlib.util.find_spec("timestral") is not None
        and importlib.util.find_spec("torch") is not None
    )


class TimestralModel:
    """Batch adapter: ragged series in, ``(B, H, 21)`` quantiles out."""

    def __init__(self, forecaster: Any) -> None:
        self._forecaster = forecaster
        self._levels = tuple(float(level) for level in forecaster.quantile_levels)

    def forecast(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        # Timestral takes one (B, T) block; shorter series are padded at the
        # start with NaN, which it reads as missing.
        length = max(len(values) for values in series)
        context = np.full((len(series), length), np.nan, dtype=np.float32)
        for row, values in enumerate(series):
            context[row, length - len(values) :] = values
        result = self._forecaster.forecast(context, prediction_length=horizon)
        quantiles = result.quantiles[:, 0].detach().cpu().numpy().astype(np.float64)
        return monotone(on_grid(quantiles, self._levels))


def on_grid(quantiles: np.ndarray, levels: Sequence[float]) -> np.ndarray:
    """Quantiles on the service's 21-level grid, interpolating if a checkpoint
    answers on other levels (beyond its outermost levels the edge value holds)."""
    if len(levels) == len(QUANTILE_LEVELS) and np.allclose(levels, QUANTILE_LEVELS):
        return quantiles
    flat = quantiles.reshape(-1, quantiles.shape[-1])
    mapped = np.stack([np.interp(QUANTILE_LEVELS, levels, row) for row in flat])
    return mapped.reshape(*quantiles.shape[:-1], len(QUANTILE_LEVELS))


class TimestralProvider:
    def __init__(
        self,
        repo_id: str,
        *,
        revision: str = "main",
        token: str | None = None,
        threads: int | None = None,
    ) -> None:
        parameters, download_bytes = CHECKPOINTS[repo_id]
        self.repo_id = repo_id
        self.revision = revision
        self.token = token
        self.threads = threads
        self.spec = ModelSpec(
            id=repo_id,
            family="timestral",
            label=f"Timestral {repo_id.rsplit('-', 1)[-1]}",
            licence=LICENCE,
            levels=QUANTILE_LEVELS,
            max_context=MAX_CONTEXT_LENGTH,
            max_horizon=MAX_HORIZON,
            parameters=parameters,
            download_bytes=download_bytes,
            source=f"https://huggingface.co/{repo_id}",
            revision=revision,
        )

    def _snapshot(self, cache_dir: Path, *, local_only: bool) -> Path:
        from huggingface_hub import snapshot_download

        return Path(
            snapshot_download(
                self.repo_id,
                revision=self.revision,
                cache_dir=cache_dir / "huggingface",
                token=self.token,
                local_files_only=local_only,
                allow_patterns=list(FILES),
            )
        )

    def is_downloaded(self, cache_dir: Path) -> bool:
        try:
            path = self._snapshot(cache_dir, local_only=True)
        except Exception:
            return False
        return all((path / name).is_file() for name in FILES)

    def download(self, cache_dir: Path, progress: Progress) -> None:
        progress(0.0)
        self._snapshot(cache_dir, local_only=False)
        progress(1.0)

    def load(self, cache_dir: Path) -> TimestralModel:
        import torch
        from timestral import TimestralForecaster

        if self.threads:
            torch.set_num_threads(self.threads)
        path = self._snapshot(cache_dir, local_only=True)
        forecaster = TimestralForecaster.from_pretrained(path, device="cpu")
        return TimestralModel(forecaster)

    def resolved_revision(self, cache_dir: Path) -> str | None:
        """The Hub commit the cached weights came from (the snapshot folder name)."""
        try:
            return self._snapshot(cache_dir, local_only=True).name
        except Exception:
            return None


def timestral_providers(
    checkpoints: Sequence[str],
    *,
    revision: str = "main",
    token: str | None = None,
    threads: int | None = None,
) -> list[TimestralProvider]:
    """One provider per checkpoint, named ``repo`` or ``repo@revision``.

    Every checkpoint is a Hub repository with commits of its own, so a
    deployment that pins its weights names a commit per checkpoint. A
    checkpoint without one uses ``revision``.
    """
    revisions: dict[str, str] = {}
    for checkpoint in checkpoints:
        repo_id, _, own_revision = checkpoint.partition("@")
        revisions[repo_id] = own_revision or revision
    unknown = sorted(set(revisions) - set(CHECKPOINTS))
    if unknown:
        raise ValueError(f"Unknown Timestral checkpoints: {', '.join(unknown)}")
    return [
        TimestralProvider(repo_id, revision=pinned, token=token, threads=threads)
        for repo_id, pinned in revisions.items()
    ]
