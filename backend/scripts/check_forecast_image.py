"""Fail the forecast image build when its pretrained models cannot run.

The service offers Timestral only where torch and the timestral package are
installed (the service's ``timestral`` extra); without them it starts and
offers the baselines alone. This checks that the image carries both, that
torch computes on this interpreter, and that the service would offer every
Timestral checkpoint. No weights are downloaded.
"""

import sys


def check_pretrained_models():
    import torch
    from off_key_core.models.adaptive import TIMESTRAL_CHECKPOINTS
    from off_key_forecast.config.config import ForecastSettings
    from off_key_forecast.providers import default_providers, timestral_installed
    from timestral import TimestralForecaster

    if not timestral_installed():
        raise RuntimeError("the timestral extra is not installed")
    if not callable(getattr(TimestralForecaster, "from_pretrained", None)):
        raise RuntimeError("timestral has no TimestralForecaster.from_pretrained")
    product = torch.ones(2, 3) @ torch.ones(3, 2)
    if product.tolist() != [[3.0, 3.0], [3.0, 3.0]]:
        raise RuntimeError("torch does not compute on this interpreter")
    if "+cpu" not in torch.__version__ or torch.cuda.is_available():
        raise RuntimeError(f"expected the CPU build of torch, got {torch.__version__}")
    providers = default_providers(ForecastSettings().config)
    offered = {provider.spec.id for provider in providers}
    missing = sorted(set(TIMESTRAL_CHECKPOINTS) - offered)
    if missing:
        raise RuntimeError(f"the service does not offer {', '.join(missing)}")
    print(f"Forecast image carries torch {torch.__version__} and timestral")


if __name__ == "__main__":
    try:
        check_pretrained_models()
    except (ImportError, RuntimeError) as error:
        sys.exit(
            f"The forecast image cannot run its pretrained models: {error}. "
            "backend/Dockerfile installs the forecast service with its extras; "
            "keep torch and timestral in backend/uv.lock."
        )
