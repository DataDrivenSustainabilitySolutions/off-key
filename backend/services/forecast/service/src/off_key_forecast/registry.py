"""The models the service offers, their download state, and loaded instances.

Weights download on first use (or on request) into the cache directory, one
download at a time, in the background. A model that is downloading or failed
never blocks the models that are ready.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from off_key_core.config.logs import logger
from off_key_core.schemas.forecast import ForecastModelInfo, ModelStatus

from .providers.base import LoadedModel, Provider


class UnknownModel(LookupError):
    pass


class ModelNotReady(RuntimeError):
    def __init__(self, info: ForecastModelInfo) -> None:
        super().__init__(f"Model {info.id} is {info.status}")
        self.info = info


@dataclass
class _State:
    status: ModelStatus
    revision: str | None = None
    progress: float | None = None
    error: str | None = None
    download: Future[None] | None = None


class ModelRegistry:
    def __init__(self, providers: Iterable[Provider], cache_dir: Path) -> None:
        self._providers = {provider.spec.id: provider for provider in providers}
        self._cache_dir = cache_dir
        self._lock = threading.Lock()
        self._load_lock = threading.Lock()
        self._loaded: dict[str, LoadedModel] = {}
        self._downloads = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="forecast-download"
        )
        self._states = {
            model_id: _State("not_downloaded", provider.spec.revision)
            for model_id, provider in self._providers.items()
        }
        for provider in self._providers.values():
            if provider.is_downloaded(cache_dir):
                self._mark_ready(provider)

    def models(self) -> list[ForecastModelInfo]:
        return [self.info(model_id) for model_id in self._providers]

    def info(self, model_id: str) -> ForecastModelInfo:
        provider = self._provider(model_id)
        with self._lock:
            state = self._states[model_id]
            spec = provider.spec
            return ForecastModelInfo(
                id=spec.id,
                family=spec.family,
                label=spec.label,
                parameters=spec.parameters,
                download_bytes=spec.download_bytes,
                licence=spec.licence,
                source=spec.source,
                revision=state.revision,
                levels=spec.levels,
                max_context=spec.max_context,
                max_horizon=spec.max_horizon,
                status=state.status,
                progress=state.progress,
                error=state.error,
            )

    def request_download(self, model_id: str) -> ForecastModelInfo:
        """Start a download unless the model is ready or already downloading.

        A failed download starts again, so a transient network error is retried
        by asking once more.
        """
        provider = self._provider(model_id)
        with self._lock:
            state = self._states[model_id]
            if state.status in {"not_downloaded", "failed"}:
                state.status, state.progress, state.error = "downloading", 0.0, None
                state.download = self._downloads.submit(self._download, provider)
        return self.info(model_id)

    def get(self, model_id: str) -> LoadedModel:
        """The loaded model; a model not downloaded yet starts downloading."""
        provider = self._provider(model_id)
        with self._lock:
            loaded = self._loaded.get(model_id)
            if loaded is not None:
                return loaded
            ready = self._states[model_id].status == "ready"
        if not ready:
            raise ModelNotReady(self.request_download(model_id))
        # A separate lock: two first requests load the weights once, while status
        # reads and other models' forecasts carry on.
        with self._load_lock:
            with self._lock:
                loaded = self._loaded.get(model_id)
            if loaded is None:
                logger.info("event=forecast.model_load model=%s", model_id)
                loaded = provider.load(self._cache_dir)
                with self._lock:
                    self._loaded[model_id] = loaded
            return loaded

    def wait_for_downloads(self) -> None:
        """Block until queued downloads finish (tests and shutdown)."""
        with self._lock:
            pending = [
                state.download
                for state in self._states.values()
                if state.download is not None
            ]
        for future in pending:
            future.exception()

    def close(self) -> None:
        self._downloads.shutdown(wait=False, cancel_futures=True)

    def _download(self, provider: Provider) -> None:
        model_id = provider.spec.id
        logger.info("event=forecast.download_started model=%s", model_id)

        def progress(fraction: float) -> None:
            with self._lock:
                self._states[model_id].progress = min(max(fraction, 0.0), 1.0)

        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            provider.download(self._cache_dir, progress)
            if not provider.is_downloaded(self._cache_dir):
                raise RuntimeError("Download finished without complete weights")
        except Exception as exc:
            logger.exception("event=forecast.download_failed model=%s", model_id)
            with self._lock:
                state = self._states[model_id]
                state.status, state.progress = "failed", None
                state.error = f"{type(exc).__name__}: {exc}"[:500]
            return
        logger.info("event=forecast.download_finished model=%s", model_id)
        self._mark_ready(provider)

    def _mark_ready(self, provider: Provider) -> None:
        # Providers that pin weights by a moving reference (a Hub branch) report
        # the exact commit they hold, so a run records which weights it used.
        resolve = getattr(provider, "resolved_revision", None)
        revision = resolve(self._cache_dir) if resolve else None
        with self._lock:
            state = self._states[provider.spec.id]
            state.status, state.progress, state.error = "ready", None, None
            state.revision = revision or provider.spec.revision

    def _provider(self, model_id: str) -> Provider:
        try:
            return self._providers[model_id]
        except KeyError:
            raise UnknownModel(model_id) from None
