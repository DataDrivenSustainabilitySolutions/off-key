"""Forecasting models the service can offer."""

from collections.abc import Sequence

from .base import LoadedModel, ModelSpec, Progress, Provider
from .naive import SeasonalNaiveProvider, naive_providers


def default_providers(naive_season_lengths: Sequence[int]) -> list[Provider]:
    """Every provider this build offers, in the order the catalog lists them."""
    return [*naive_providers(naive_season_lengths)]


__all__ = [
    "LoadedModel",
    "ModelSpec",
    "Progress",
    "Provider",
    "SeasonalNaiveProvider",
    "default_providers",
    "naive_providers",
]
