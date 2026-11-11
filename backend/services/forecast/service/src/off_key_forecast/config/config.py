"""Environment settings of the forecast service."""

from functools import lru_cache
from pathlib import Path

from off_key_core.config.validation import SECRETS_DIR
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForecastConfig(BaseModel):
    api_host: str
    api_port: int = Field(ge=1, le=65535)
    cache_dir: Path
    api_token: SecretStr | None
    naive_season_lengths: tuple[int, ...]
    timestral_models: tuple[str, ...]
    timestral_revision: str
    hub_token: SecretStr | None
    torch_threads: int = Field(ge=1, le=64)

    model_config = ConfigDict(extra="forbid", frozen=True)


class ForecastSettings(BaseSettings):
    # A deployment hands the tokens over as Docker secrets.
    model_config = SettingsConfigDict(
        case_sensitive=True, extra="ignore", secrets_dir=SECRETS_DIR
    )

    FORECAST_API_HOST: str = "0.0.0.0"
    FORECAST_API_PORT: int = Field(default=8020, ge=1, le=65535)
    # Weights download here on first use and stay; mount a volume in deployments.
    FORECAST_CACHE_DIR: Path = Path("/models")
    # Shared with callers on the app network; unset only for local development.
    FORECAST_API_TOKEN: SecretStr | None = None
    # Season lengths offered by the built-in seasonal-naive baseline.
    FORECAST_NAIVE_SEASON_LENGTHS: str = "1,24,96,144,168,288"
    # Timestral checkpoints offered when the timestral extra is installed; each
    # downloads on first use. The revision is a Hub branch, tag or commit; a
    # checkpoint named ``repo@revision`` uses its own, which is how a deployment
    # pins weights (each checkpoint's repository has its own commits).
    FORECAST_TIMESTRAL_MODELS: str = (
        "mistralai/Timestral-5M,mistralai/Timestral-28M,"
        "mistralai/Timestral-123M,mistralai/Timestral-209M"
    )
    FORECAST_TIMESTRAL_REVISION: str = "main"
    HF_TOKEN: SecretStr | None = None
    FORECAST_TORCH_THREADS: int = Field(default=2, ge=1, le=64)

    @property
    def config(self) -> ForecastConfig:
        lengths = tuple(
            int(item) for item in self.FORECAST_NAIVE_SEASON_LENGTHS.split(",") if item
        )
        if any(length < 1 for length in lengths):
            raise ValueError("FORECAST_NAIVE_SEASON_LENGTHS must be positive")
        token = self.FORECAST_API_TOKEN
        hub_token = self.HF_TOKEN
        return ForecastConfig(
            api_host=self.FORECAST_API_HOST,
            api_port=self.FORECAST_API_PORT,
            cache_dir=self.FORECAST_CACHE_DIR,
            api_token=token if token and token.get_secret_value() else None,
            naive_season_lengths=lengths,
            timestral_models=tuple(
                item.strip()
                for item in self.FORECAST_TIMESTRAL_MODELS.split(",")
                if item.strip()
            ),
            timestral_revision=self.FORECAST_TIMESTRAL_REVISION,
            hub_token=hub_token if hub_token and hub_token.get_secret_value() else None,
            torch_threads=self.FORECAST_TORCH_THREADS,
        )


@lru_cache(maxsize=1)
def get_forecast_settings() -> ForecastSettings:
    return ForecastSettings()


def clear_forecast_settings_cache() -> None:
    get_forecast_settings.cache_clear()
