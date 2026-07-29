"""Typed martingale tracker factory and bounded ensemble controller."""

from typing import Any

import numpy as np


class RestartedMartingaleAlarmController:
    """Legacy power/restarted controller retained for checkpoint compatibility."""

    BETTING_FUNCTION = "power"
    ALARM_STATISTIC = "restarted_martingale"
    FIXED_RESTARTED_VILLE_THRESHOLD = 100.0

    def __init__(
        self,
        *,
        epsilon: float,
        restarted_ville_threshold: float = FIXED_RESTARTED_VILLE_THRESHOLD,
        alarm_count: int = 0,
        tested_count: int = 0,
        martingale: Any = None,
        alarm_active: bool = False,
    ) -> None:
        self.epsilon = float(epsilon)
        self._validate_threshold(restarted_ville_threshold)
        self.restarted_ville_threshold = float(restarted_ville_threshold)
        self.alarm_count = int(alarm_count)
        self.tested_count = int(tested_count)
        self._alarm_active = bool(alarm_active)
        self._martingale = martingale or self._new_martingale()

    @classmethod
    def from_config(cls, config: Any) -> "RestartedMartingaleAlarmController":
        return cls(
            epsilon=config.epsilon,
            restarted_ville_threshold=config.restarted_ville_threshold,
        )

    @classmethod
    def _validate_threshold(cls, value: float) -> None:
        if float(value) != cls.FIXED_RESTARTED_VILLE_THRESHOLD:
            raise ValueError(
                "restarted_ville_threshold is fixed at "
                f"{cls.FIXED_RESTARTED_VILLE_THRESHOLD:g}."
            )

    def _new_martingale(self) -> Any:
        from nonconform.martingales import AlarmConfig, PowerMartingale

        return PowerMartingale(
            epsilon=self.epsilon,
            alarm_config=AlarmConfig(
                restarted_ville_threshold=self.restarted_ville_threshold
            ),
        )

    def update(self, p_value: float) -> dict[str, Any]:
        state = self._martingale.update(p_value)
        self.tested_count += 1
        threshold_crossed = (
            "restarted_ville" in state.triggered_alarms
            or state.restarted_martingale >= self.restarted_ville_threshold
        )
        alarm_fired = threshold_crossed and not self._alarm_active
        self._alarm_active = threshold_crossed
        if alarm_fired:
            self.alarm_count += 1

        if p_value == 0.0:
            log_e_value = float("inf") if self.epsilon < 1.0 else 0.0
        else:
            log_e_value = float(
                np.log(self.epsilon) + (self.epsilon - 1.0) * np.log(p_value)
            )
        max_log_float = float(np.log(np.finfo(float).max))
        e_value = (
            float(np.exp(log_e_value))
            if np.isfinite(log_e_value) and log_e_value <= max_log_float
            else float("inf")
        )
        finite_e_value = e_value if np.isfinite(e_value) else None
        restarted_martingale = float(state.restarted_martingale)
        finite_restarted_martingale = (
            restarted_martingale if np.isfinite(restarted_martingale) else None
        )
        log_restarted_martingale = float(state.log_restarted_martingale)
        finite_log_restarted_martingale = (
            log_restarted_martingale if np.isfinite(log_restarted_martingale) else None
        )
        return {
            "betting_function": self.BETTING_FUNCTION,
            "alarm_statistic": self.ALARM_STATISTIC,
            "epsilon": self.epsilon,
            "e_value": finite_e_value,
            "e_value_is_infinite": finite_e_value is None,
            "log_e_value": log_e_value if np.isfinite(log_e_value) else None,
            "restarted_ville_threshold": self.restarted_ville_threshold,
            "restarted_martingale": finite_restarted_martingale,
            "restarted_martingale_is_infinite": (finite_restarted_martingale is None),
            "log_restarted_martingale": finite_log_restarted_martingale,
            "alarm_fired": alarm_fired,
            "alarm_active": self._alarm_active,
            "alarm_count": self.alarm_count,
            "tested_count": self.tested_count,
        }


_ALARM_TRIGGER_NAMES = {
    "martingale": "ville",
    "restarted_martingale": "restarted_ville",
    "cusum": "cusum",
    "shiryaev_roberts": "shiryaev_roberts",
}
_ALARM_CONFIG_FIELDS = {
    "martingale": "ville_threshold",
    "restarted_martingale": "restarted_ville_threshold",
    "cusum": "cusum_threshold",
    "shiryaev_roberts": "shiryaev_roberts_threshold",
}
_STATE_VALUE_FIELDS = {
    "martingale": ("martingale", "log_martingale"),
    "restarted_martingale": (
        "restarted_martingale",
        "log_restarted_martingale",
    ),
    "cusum": ("cusum", "log_cusum"),
    "shiryaev_roberts": ("shiryaev_roberts", "log_shiryaev_roberts"),
}


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _statistic_payload(state: Any, statistic: str) -> dict[str, Any]:
    value_field, log_field = _STATE_VALUE_FIELDS[statistic]
    value = float(getattr(state, value_field))
    log_value = float(getattr(state, log_field))
    return {
        "value": _finite_or_none(value),
        "is_infinite": bool(np.isposinf(value)),
        "log_value": _finite_or_none(log_value),
    }


class MartingaleTrackerController:
    """One configured betting process and selected alarm statistic."""

    def __init__(
        self,
        config: Any,
        *,
        alarm_count: int = 0,
        tested_count: int = 0,
        martingale: Any = None,
        alarm_active: bool = False,
    ) -> None:
        self.config = config
        self.alarm_count = int(alarm_count)
        self.tested_count = int(tested_count)
        self._alarm_active = bool(alarm_active)
        self._martingale = martingale or self._new_martingale()

    def _new_martingale(self) -> Any:
        from nonconform.martingales import (
            AlarmConfig,
            PowerMartingale,
            SimpleJumperMartingale,
            SimpleMixtureMartingale,
        )

        alarm_config = AlarmConfig(
            **{
                _ALARM_CONFIG_FIELDS[self.config.alarm_statistic]: (
                    self.config.threshold
                )
            }
        )
        if self.config.betting_function == "power":
            return PowerMartingale(
                epsilon=self.config.epsilon,
                alarm_config=alarm_config,
            )
        if self.config.betting_function == "simple_mixture":
            return SimpleMixtureMartingale(
                epsilons=self.config.epsilons,
                n_grid=self.config.n_grid,
                min_epsilon=self.config.min_epsilon,
                alarm_config=alarm_config,
            )
        if self.config.betting_function == "simple_jumper":
            return SimpleJumperMartingale(
                jump=self.config.jump,
                alarm_config=alarm_config,
            )
        raise ValueError(
            f"Unsupported martingale betting function: {self.config.betting_function}"
        )

    def _log_e_value(self, p_value: float, previous_log_martingale: float) -> float:
        if self.config.betting_function == "power":
            if p_value == 0.0:
                return float("inf") if self.config.epsilon < 1.0 else 0.0
            return float(
                np.log(self.config.epsilon)
                + (self.config.epsilon - 1.0) * np.log(p_value)
            )

        current_log_martingale = float(self._martingale.state.log_martingale)
        if np.isfinite(previous_log_martingale) and np.isfinite(current_log_martingale):
            return current_log_martingale - previous_log_martingale
        if np.isposinf(current_log_martingale) and not np.isposinf(
            previous_log_martingale
        ):
            return float("inf")
        # Once aggregate capital has saturated at +inf, a finite ratio cannot be
        # reconstructed from the public state. Keep the JSON representation honest.
        return float("nan")

    def update(self, p_value: float) -> dict[str, Any]:
        previous_log_martingale = float(self._martingale.state.log_martingale)
        state = self._martingale.update(p_value)
        self.tested_count += 1

        statistic = self.config.alarm_statistic
        selected = _statistic_payload(state, statistic)
        raw_selected_value = float(getattr(state, _STATE_VALUE_FIELDS[statistic][0]))
        trigger_name = _ALARM_TRIGGER_NAMES[statistic]
        threshold_crossed = (
            trigger_name in state.triggered_alarms
            or raw_selected_value >= self.config.threshold
        )
        alarm_fired = threshold_crossed and not self._alarm_active
        self._alarm_active = threshold_crossed
        if alarm_fired:
            self.alarm_count += 1

        log_e_value = self._log_e_value(p_value, previous_log_martingale)
        max_log_float = float(np.log(np.finfo(float).max))
        e_value = (
            float(np.exp(log_e_value))
            if np.isfinite(log_e_value) and log_e_value <= max_log_float
            else None
        )
        statistics = {
            name: _statistic_payload(state, name) for name in _STATE_VALUE_FIELDS
        }
        parameters = self.config.model_dump(
            exclude={
                "tracker_id",
                "betting_function",
                "alarm_statistic",
                "threshold",
            },
            exclude_none=True,
        )
        return {
            "tracker_id": self.config.tracker_id,
            "betting_function": self.config.betting_function,
            "betting_parameters": parameters,
            "alarm_statistic": statistic,
            "statistic_value": selected["value"],
            "statistic_is_infinite": selected["is_infinite"],
            "log_statistic_value": selected["log_value"],
            "statistics": statistics,
            "e_value": e_value,
            "e_value_is_infinite": bool(np.isposinf(log_e_value)),
            "log_e_value": _finite_or_none(log_e_value),
            "threshold": float(self.config.threshold),
            "alarm_fired": alarm_fired,
            "alarm_active": self._alarm_active,
            "alarm_count": self.alarm_count,
            "tested_count": self.tested_count,
        }


class MartingaleAlarmController:
    """Bounded ensemble of martingale trackers sharing one p-value stream."""

    def __init__(self, trackers: list[MartingaleTrackerController]) -> None:
        if not trackers:
            raise ValueError("At least one martingale tracker is required")
        self.trackers = trackers

    @classmethod
    def from_config(cls, config: Any) -> "MartingaleAlarmController":
        return cls(
            [MartingaleTrackerController(tracker) for tracker in config.trackers]
        )

    @classmethod
    def from_legacy(cls, controller: Any) -> "MartingaleAlarmController":
        from off_key_core.schemas.radar import PowerMartingaleTrackerConfig

        config = PowerMartingaleTrackerConfig(
            tracker_id="primary",
            epsilon=controller.epsilon,
            alarm_statistic="restarted_martingale",
            threshold=controller.restarted_ville_threshold,
        )
        return cls(
            [
                MartingaleTrackerController(
                    config,
                    alarm_count=controller.alarm_count,
                    tested_count=controller.tested_count,
                    martingale=controller._martingale,
                    alarm_active=controller._alarm_active,
                )
            ]
        )

    @property
    def alarm_count(self) -> int:
        return sum(tracker.alarm_count for tracker in self.trackers)

    @property
    def tested_count(self) -> int:
        return max((tracker.tested_count for tracker in self.trackers), default=0)

    def update(self, p_value: float) -> dict[str, Any]:
        tracker_results = [tracker.update(p_value) for tracker in self.trackers]
        primary = tracker_results[0]
        primary_restarted = primary["statistics"]["restarted_martingale"]
        fired_tracker_ids = [
            result["tracker_id"] for result in tracker_results if result["alarm_fired"]
        ]
        betting_parameters = primary["betting_parameters"]
        return {
            "tracker_results": tracker_results,
            "fired_tracker_ids": fired_tracker_ids,
            "betting_function": primary["betting_function"],
            "betting_parameters": betting_parameters,
            "alarm_statistic": primary["alarm_statistic"],
            "epsilon": betting_parameters.get("epsilon"),
            "e_value": primary["e_value"],
            "e_value_is_infinite": primary["e_value_is_infinite"],
            "log_e_value": primary["log_e_value"],
            "threshold": primary["threshold"],
            # Legacy projection of the primary betting process.
            "restarted_ville_threshold": primary["threshold"],
            "restarted_martingale": primary_restarted["value"],
            "restarted_martingale_is_infinite": primary_restarted["is_infinite"],
            "log_restarted_martingale": primary_restarted["log_value"],
            "alarm_fired": bool(fired_tracker_ids),
            "alarm_active": any(result["alarm_active"] for result in tracker_results),
            "alarm_count": self.alarm_count,
            "tested_count": self.tested_count,
        }
