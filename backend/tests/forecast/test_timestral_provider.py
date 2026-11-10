"""The Timestral provider's adapter and Hub cache handling, without the model.

The model itself (torch and the timestral package) is an optional extra of the
service; these tests cover what off-key adds around it.
"""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from off_key_core.schemas.forecast import QUANTILE_LEVELS
from off_key_forecast.providers.timestral import (
    TimestralModel,
    TimestralProvider,
    on_grid,
    timestral_providers,
)
from off_key_forecast.registry import ModelRegistry


class Tensorish(np.ndarray):
    """Enough of a torch tensor for the adapter: detach, cpu, numpy."""

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self)


class RecordingForecaster:
    def __init__(self, levels=QUANTILE_LEVELS) -> None:
        self.quantile_levels = levels
        self.calls = []

    def forecast(self, context, prediction_length):
        self.calls.append(context.copy())
        batch = context.shape[0]
        last = np.nan_to_num(context[:, -1])
        offsets = np.linspace(-1, 1, len(self.quantile_levels))
        quantiles = (
            last[:, None, None, None]
            + np.zeros((batch, 1, prediction_length, 1))
            + offsets
        )
        return SimpleNamespace(quantiles=quantiles.view(Tensorish))


def _hub_snapshot(cache_dir: Path, repo_id: str, commit: str) -> Path:
    """Lay out the Hub cache the way huggingface_hub leaves a finished download."""
    repo = cache_dir / "huggingface" / f"models--{repo_id.replace('/', '--')}"
    snapshot = repo / "snapshots" / commit
    snapshot.mkdir(parents=True)
    for name in ("config.json", "model.safetensors"):
        (snapshot / name).write_text("{}")
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text(commit)
    return snapshot


def test_adapter_pads_ragged_series_at_the_start_and_returns_the_grid():
    forecaster = RecordingForecaster()
    quantiles = TimestralModel(forecaster).forecast(
        [np.array([1.0, 2.0, 3.0]), np.array([7.0])], 4
    )

    sent = forecaster.calls[0]
    assert sent.shape == (2, 3)
    assert np.isnan(sent[1, :2]).all() and sent[1, 2] == 7.0
    assert quantiles.shape == (2, 4, len(QUANTILE_LEVELS))
    assert quantiles[1, 0, QUANTILE_LEVELS.index(0.5)] == pytest.approx(7.0)


def test_other_quantile_levels_are_interpolated_onto_the_grid():
    levels = (0.1, 0.5, 0.9)
    quantiles = np.array([[[-1.0, 0.0, 1.0]]])
    mapped = on_grid(quantiles, levels)
    assert mapped.shape == (1, 1, len(QUANTILE_LEVELS))
    assert mapped[0, 0, QUANTILE_LEVELS.index(0.5)] == 0.0
    assert mapped[0, 0, QUANTILE_LEVELS.index(0.3)] == pytest.approx(-0.5)
    # Beyond the checkpoint's outermost levels the edge value holds.
    assert mapped[0, 0, 0] == -1.0 and mapped[0, 0, -1] == 1.0


def test_checkpoints_are_offered_by_name_with_their_sizes():
    providers = timestral_providers(
        ["mistralai/Timestral-5M", "mistralai/Timestral-28M"]
    )
    spec = providers[1].spec
    assert (spec.label, spec.parameters, spec.download_bytes) == (
        "Timestral 28M",
        28_000_000,
        111_000_000,
    )
    assert spec.levels == QUANTILE_LEVELS
    with pytest.raises(ValueError, match="Unknown Timestral"):
        timestral_providers(["mistralai/Timestral-1B"])


def test_cached_weights_are_ready_offline_and_report_their_commit(tmp_path):
    provider = TimestralProvider("mistralai/Timestral-5M")
    assert provider.is_downloaded(tmp_path) is False

    _hub_snapshot(tmp_path, "mistralai/Timestral-5M", "a" * 40)
    registry = ModelRegistry([provider], tmp_path)
    info = registry.info("mistralai/Timestral-5M")

    assert info.status == "ready"
    assert info.revision == "a" * 40
    assert info.licence.startswith("Mistral AI Modified MIT")


def test_a_snapshot_missing_its_weights_is_not_ready(tmp_path):
    snapshot = _hub_snapshot(tmp_path, "mistralai/Timestral-5M", "b" * 40)
    (snapshot / "model.safetensors").unlink()
    assert TimestralProvider("mistralai/Timestral-5M").is_downloaded(tmp_path) is False
