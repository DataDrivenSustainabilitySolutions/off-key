"""Forecasting models the service can offer."""

from ..config.config import ForecastConfig
from .base import LoadedModel, ModelSpec, Progress, Provider
from .naive import SeasonalNaiveProvider, naive_providers
from .timestral import TimestralProvider, timestral_installed, timestral_providers


def default_providers(config: ForecastConfig) -> list[Provider]:
    """Every provider this build offers, in the order the catalog lists them.

    Timestral needs the service's ``timestral`` extra (torch); without it only
    the built-in baselines are offered.
    """
    providers: list[Provider] = [*naive_providers(config.naive_season_lengths)]
    if timestral_installed():
        token = config.hub_token.get_secret_value() if config.hub_token else None
        providers += timestral_providers(
            config.timestral_models,
            revision=config.timestral_revision,
            token=token,
            threads=config.torch_threads,
        )
    return providers


__all__ = [
    "LoadedModel",
    "ModelSpec",
    "Progress",
    "Provider",
    "SeasonalNaiveProvider",
    "TimestralProvider",
    "default_providers",
    "naive_providers",
    "timestral_installed",
    "timestral_providers",
]
