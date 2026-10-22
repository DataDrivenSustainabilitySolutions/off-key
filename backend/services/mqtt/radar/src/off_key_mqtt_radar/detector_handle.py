"""Run one detector and turn its unexpected errors into execution failures."""

import logging
from datetime import datetime
from typing import Any, Protocol

from .execution_errors import FatalExecutionError, ObservationRejected
from .models import AnomalyResult

logger = logging.getLogger(__name__)


class DetectionService(Protocol):
    """Every detector operation the service calls; detectors define each one."""

    processed_count: int
    last_checkpoint: int

    def process_data_point(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult: ...

    def get_model_info(self) -> dict[str, Any]: ...

    def export_checkpoint(self) -> dict[str, Any]: ...

    def refresh_background_state(self) -> None: ...

    def get_pipeline_state(self) -> dict[str, Any] | None: ...

    def attach_observation_metadata(
        self, timestamp: datetime, input_timestamps: dict[str, Any]
    ) -> None: ...

    def shutdown(self) -> None: ...


class DetectorHandle:
    """Own a detector for the service; any unexpected error ends the run.

    A detector that raised may have mutated its model, so no substitute result
    is produced. The service fences the execution and keeps the last checkpoint.
    """

    def __init__(self, primary_service: DetectionService) -> None:
        self.primary_service = primary_service

    async def stop(self) -> None:
        """Release resources held by the detector."""
        self.primary_service.shutdown()

    def process(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult:
        try:
            return self.primary_service.process_data_point(data, topic, charger_id)
        except (FatalExecutionError, ObservationRejected):
            raise
        except Exception as error:
            logger.exception("event=radar.model_error")
            raise FatalExecutionError(
                f"Detector failed: {type(error).__name__}: {error}"
            ) from error

    def get_health_info(self) -> dict[str, Any]:
        """Read model statistics; the serial owner refreshes background state."""
        return {
            "state": "healthy",
            "primary_service_stats": self.primary_service.get_model_info(),
        }
