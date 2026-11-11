"""Runs whose calibration step keeps adapting a boundary on the scores.

Any detectors can feed it: detectors fitted once, detectors that learn every
observation, or both. They warm up and fill the calibration window as a fixed
split's do. The calibration window then seeds the boundary instead of
freezing a threshold, and every scored observation updates it. The exceedance
rule alarms on scores above the boundary. Results, checkpoints and health
read as a threshold run's.
"""

from __future__ import annotations

from typing import Any

from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig

from .adaptive_detector import AdaptiveStreamState
from .boundary import Judgement, ScoreBoundary, adapts
from .mixed_detector import MixedDetectionService
from .models import AnomalyResult


class BoundaryDetectionService(MixedDetectionService):
    """Detectors of any kind under a boundary that follows their scores."""

    # A run of detectors fitted once takes its windows from the static settings.
    _monitoring_settings = (AdaptiveStreamConfig, StaticBaselineConfig)

    @staticmethod
    def _runs(plan) -> bool:
        return adapts(plan)

    def _initialize_fresh(self) -> None:
        super()._initialize_fresh()
        self.boundary = ScoreBoundary(self.plan)

    def _restore(self, checkpoint: dict[str, Any]) -> None:
        boundary = checkpoint.get("boundary")
        expected = ScoreBoundary(self.plan)
        if not isinstance(boundary, ScoreBoundary) or (
            boundary.settings != expected.settings
        ):
            raise ValueError("Checkpoint is missing its calibration step")
        if (
            AdaptiveStreamState(checkpoint["adaptive_state"])
            == AdaptiveStreamState.OPERATIONAL
            and not boundary.started
        ):
            raise ValueError("Operational checkpoint has no calibrated boundary")
        self.boundary = boundary
        super()._restore(checkpoint)

    def _restore_fusion(self, checkpoint: dict[str, Any]) -> None:
        """The boundary comes back as it was; nothing is frozen again."""

    def export_checkpoint(self) -> dict[str, Any]:
        checkpoint = super().export_checkpoint()
        checkpoint["boundary"] = self.boundary
        return checkpoint

    def _process_calibration(self, data, topic, charger_id, started) -> AnomalyResult:
        """Keep every detector's score, or the observation for a detector that
        is fitted after the window; the boundary starts from them all."""
        scores = self._streaming_scores(data)
        self._learn(data)
        if self.batch.detector_ids:
            self.batch.calibration.append(self.batch.vector(data))
        self.calibration_scores.append(scores)
        self.calibration_count += 1
        self.processed_count += 1
        if self.calibration_count >= self.adaptive_config.calibration_window_size:
            if self.batch.detector_ids:
                self.state = AdaptiveStreamState.FITTING
                self._submit_fit()
            else:
                self._freeze_fusion()
                self.state = AdaptiveStreamState.OPERATIONAL
                self._log_calibrated()
        return self._result(data, 0.0, False, "calibration", topic, charger_id, started)

    def _freeze_fusion(self) -> None:
        """Seed the boundary with the calibration window; no threshold freezes."""
        self._start_comparison(self.calibration_scores)
        self.boundary.start(self.calibration_scores)
        # The boundary keeps what it needs of them.
        self.calibration_scores = []
        self.threshold = self.boundary.next_threshold()
        self.severity_scale = max(abs(self.threshold), self.boundary.spread())

    def _process_operational(self, data, topic, charger_id, started) -> AnomalyResult:
        judgement = self.boundary.judge(self._detector_scores(data))
        # One detector's raw score meets the boundary; ranks have no such band.
        self._expect(judgement.threshold if judgement.surprises is None else None)
        self._learn(data)
        # Only an observation every detector took in moves the boundary.
        self.boundary.learn(judgement)
        self._compare(list(judgement.scores))
        self.threshold = judgement.threshold
        self.operational_count += 1
        self.processed_count += 1
        if judgement.alarm:
            self.anomaly_count += 1
            self.severity_scale = max(abs(self.threshold), self.boundary.spread())
        self._report_detectors(judgement)
        return self._result(
            data,
            judgement.value,
            judgement.alarm,
            "operational",
            topic,
            charger_id,
            started,
        )

    def _streaming_scores(self, data: dict[str, float]) -> list[float]:
        """The scores of the detectors that learn here, in their order."""
        if self.plan.fused:
            return self._scores(data)
        return [] if self.pipeline is None else [self._score(data)]

    def _detector_scores(self, data: dict[str, float]) -> list[float]:
        """Every detector's score, in the run's order."""
        if self.plan.fused:
            return self._fused_scores(data)
        if self.pipeline is not None:
            return [self._score(data)]
        self._diagnose(self.diagnostics.select_pass, "score")
        self.diagnostics.record(self.plan.source_id, self._bound, self._bound)
        identifier = self.plan.detector_id
        score = self._batch_scores(data)[identifier]
        self._scored_features = self.batch.last_features[identifier]
        return [score]

    def _report_detectors(self, judgement: Judgement) -> None:
        if judgement.surprises is None:
            return
        # A surprise is shown as a share; how far a score is above its window
        # is in the combined value.
        self._detector_results = [
            {"detector_id": identifier, "score": score, "surprise": min(surprise, 1.0)}
            for identifier, score, surprise in zip(
                self.plan.detector_ids,
                judgement.scores,
                judgement.surprises,
                strict=True,
            )
        ]
        self._diagnose(self.diagnostics.detectors, self._detector_results)

    def get_model_info(self) -> dict[str, Any]:
        info = super().get_model_info()
        info["calibration"] = {
            **self.boundary.settings,
            "exceedances_in_a_row": self.boundary.run,
        }
        return info
