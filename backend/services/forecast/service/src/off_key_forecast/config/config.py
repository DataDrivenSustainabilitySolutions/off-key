"""Environment settings of the forecast service."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForecastConfig(BaseModel):
    api_host: str
    api_port: int = Field(ge=1, le=65535)
    cache_dir: Path
    api_token: SecretStr | None
    naive_season_lengths: tuple[int, ...]

    model_config = ConfigDict(extra="forbid", frozen=True)


class ForecastSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    FORECAST_API_HOST: str = "0.0.0.0"
    FORECAST_API_PORT: int = Field(default=8020, ge=1, le=65535)
    # Weights download here on first use and stay; mount a volume in deployments.
    FORECAST_CACHE_DIR: Path = Path("/models")
    # Shared with callers on the app network; unset only for local development.
    FORECAST_API_TOKEN: SecretStr | None = None
    # Season lengths offered by the built-in seasonal-naive baseline.
    FORECAST_NAIVE_SEASON_LENGTHS: str = "1,24,96,144,168,288"

    @property
    def config(self) -> ForecastConfig:
        lengths = tuple(
            int(item) for item in self.FORECAST_NAIVE_SEASON_LENGTHS.split(",") if item
        )
        if any(length < 1 for length in lengths):
            raise ValueError("FORECAST_NAIVE_SEASON_LENGTHS must be positive")
        token = self.FORECAST_API_TOKEN
        return ForecastConfig(
            api_host=self.FORECAST_API_HOST,
            api_port=self.FORECAST_API_PORT,
            cache_dir=self.FORECAST_CACHE_DIR,
            api_token=token if token and token.get_secret_value() else None,
            naive_season_lengths=lengths,
        )


@lru_cache(maxsize=1)
def get_forecast_settings() -> ForecastSettings:
    return ForecastSettings()


def clear_forecast_settings_cache() -> None:
    get_forecast_settings.cache_clear()
