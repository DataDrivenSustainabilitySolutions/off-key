"""Finite-horizon null calibration for CUSUM and Shiryaev-Roberts trackers."""

from __future__ import annotations

from math import ceil
from typing import Any

import numpy as np
from off_key_core.schemas.radar import (
    AutomaticAlarmThresholdConfig,
    ManualAlarmThresholdConfig,
    StaticMartingaleConfig,
)

_LOG_FLOAT_MAX = float(np.log(np.finfo(float).max))
_SIMULATION_BATCH_SIZE = 256


def _logsumexp_rows(values: np.ndarray) -> np.ndarray:
    maxima = np.max(values, axis=1)
    return maxima + np.log(np.sum(np.exp(values - maxima[:, None]), axis=1))


def _simulate_split_conformal_p_values(
    *,
    calibration_size: int,
    horizon: int,
    simulation_count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Simulate rank p-values with one shared calibration set per null path."""
    p_values = np.empty((simulation_count, horizon), dtype=np.float64)
    denominator = float(calibration_size + 1)
    for row in range(simulation_count):
        calibration_scores = np.sort(rng.random(calibration_size))
        future_scores = rng.random(horizon)
        positions = np.searchsorted(
            calibration_scores,
            future_scores,
            side="left",
        )
        p_values[row] = (calibration_size - positions + 1) / denominator
    return p_values


def _update_alarm_statistic(
    log_statistic: np.ndarray,
    log_increment: np.ndarray,
    alarm_statistic: str,
) -> np.ndarray:
    if alarm_statistic == "cusum":
        return log_increment + np.maximum(log_statistic, 0.0)
    if alarm_statistic == "shiryaev_roberts":
        return log_increment + np.logaddexp(0.0, log_statistic)
    raise ValueError(
        "Automatic threshold calibration only supports CUSUM and "
        "Shiryaev-Roberts statistics"
    )


def _maximum_log_statistic(
    p_values: np.ndarray,
    tracker: Any,
) -> np.ndarray:
    simulation_count, horizon = p_values.shape
    log_statistic = np.full(simulation_count, float("-inf"))
    maximum = np.full(simulation_count, float("-inf"))

    if tracker.betting_function == "power":
        epsilon = float(tracker.epsilon)
        for step in range(horizon):
            log_p = np.log(p_values[:, step])
            log_increment = np.log(epsilon) + (epsilon - 1.0) * log_p
            log_statistic = _update_alarm_statistic(
                log_statistic,
                log_increment,
                tracker.alarm_statistic,
            )
            maximum = np.maximum(maximum, log_statistic)
        return maximum

    if tracker.betting_function == "simple_mixture":
        epsilons = (
            np.asarray(tracker.epsilons, dtype=float)
            if tracker.epsilons is not None
            else np.linspace(
                float(tracker.min_epsilon),
                1.0,
                int(tracker.n_grid),
            )
        )
        log_capitals = np.zeros((simulation_count, len(epsilons)))
        previous_log_mixture = np.zeros(simulation_count)
        for step in range(horizon):
            log_p = np.log(p_values[:, step])[:, None]
            log_capitals += np.log(epsilons) + (epsilons - 1.0) * log_p
            current_log_mixture = _logsumexp_rows(log_capitals) - np.log(len(epsilons))
            log_increment = current_log_mixture - previous_log_mixture
            previous_log_mixture = current_log_mixture
            log_statistic = _update_alarm_statistic(
                log_statistic,
                log_increment,
                tracker.alarm_statistic,
            )
            maximum = np.maximum(maximum, log_statistic)
        return maximum

    if tracker.betting_function == "simple_jumper":
        jump = float(tracker.jump)
        epsilons = np.asarray([-1.0, 0.0, 1.0])
        log_components = np.full(
            (simulation_count, 3),
            np.log(1.0 / 3.0),
        )
        log_stay = float("-inf") if jump == 1.0 else float(np.log1p(-jump))
        log_jump = float(np.log(jump / 3.0))
        for step in range(horizon):
            previous_log_capital = _logsumexp_rows(log_components)
            log_components = np.logaddexp(
                log_stay + log_components,
                log_jump + previous_log_capital[:, None],
            )
            betting_terms = 1.0 + epsilons * (p_values[:, step, None] - 0.5)
            log_components += np.log(betting_terms)
            current_log_capital = _logsumexp_rows(log_components)
            log_increment = current_log_capital - previous_log_capital
            log_statistic = _update_alarm_statistic(
                log_statistic,
                log_increment,
                tracker.alarm_statistic,
            )
            maximum = np.maximum(maximum, log_statistic)
        return maximum

    raise ValueError(f"Unsupported betting function: {tracker.betting_function}")


def _calibrated_threshold(
    maximum_log_statistics: np.ndarray,
    false_alarm_probability: float,
) -> float:
    simulation_count = len(maximum_log_statistics)
    order_index = ceil((simulation_count + 1) * (1.0 - false_alarm_probability)) - 1
    if order_index >= simulation_count:
        raise ValueError(
            "simulation_count is too small for the requested false-alarm probability"
        )
    log_cutoff = float(np.partition(maximum_log_statistics, order_index)[order_index])
    if not np.isfinite(log_cutoff) or log_cutoff >= _LOG_FLOAT_MAX:
        raise ValueError(
            "The calibrated threshold exceeds the supported finite numeric range"
        )
    # Runtime alarm statistics are compared in linear space with >=. Move one
    # representable linear value above the sampled cutoff so tied paths remain
    # on the non-triggering side of the Monte Carlo order statistic.
    threshold = float(np.nextafter(np.exp(log_cutoff), float("inf")))
    if not np.isfinite(threshold) or threshold <= 0.0:
        raise ValueError("Automatic threshold calibration produced an invalid value")
    return threshold


def resolve_tracker_thresholds(
    config: StaticMartingaleConfig,
    *,
    calibration_size: int,
    seed: int | None,
) -> dict[str, float]:
    """Resolve manual values and calibrate automatic trackers as one ensemble."""
    thresholds = {
        tracker.tracker_id: float(tracker.threshold_config.value)
        for tracker in config.trackers
        if isinstance(tracker.threshold_config, ManualAlarmThresholdConfig)
    }
    automatic_trackers = [
        tracker
        for tracker in config.trackers
        if isinstance(tracker.threshold_config, AutomaticAlarmThresholdConfig)
    ]
    if not automatic_trackers:
        return thresholds
    if calibration_size < 1:
        raise ValueError("calibration_size must be positive")

    calibration = config.automatic_threshold_calibration
    per_tracker_probability = calibration.false_alarm_probability / len(
        automatic_trackers
    )
    maxima_by_tracker = {
        tracker.tracker_id: np.empty(calibration.simulation_count, dtype=float)
        for tracker in automatic_trackers
    }
    rng = np.random.default_rng(seed)

    for start in range(0, calibration.simulation_count, _SIMULATION_BATCH_SIZE):
        stop = min(start + _SIMULATION_BATCH_SIZE, calibration.simulation_count)
        p_values = _simulate_split_conformal_p_values(
            calibration_size=calibration_size,
            horizon=calibration.horizon,
            simulation_count=stop - start,
            rng=rng,
        )
        for tracker in automatic_trackers:
            maxima_by_tracker[tracker.tracker_id][start:stop] = _maximum_log_statistic(
                p_values, tracker
            )

    for tracker in automatic_trackers:
        thresholds[tracker.tracker_id] = _calibrated_threshold(
            maxima_by_tracker[tracker.tracker_id],
            per_tracker_probability,
        )
    return thresholds


__all__ = ["resolve_tracker_thresholds"]
