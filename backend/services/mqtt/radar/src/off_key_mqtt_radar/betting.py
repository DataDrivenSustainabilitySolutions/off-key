"""One table entry per martingale betting function.

Each entry builds the runtime nonconform martingale, gives its closed-form
log e-value where one exists, and simulates its log increments over many null
paths at once for automatic threshold calibration. Controllers look entries up
per call so pickled checkpoints never hold a reference to this table.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

Step = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class BettingFunction:
    build: Callable[[Any, Any], Any]
    closed_form_log_e: Callable[[Any, float], float | None]
    simulator: Callable[[Any, int], Step]


def _logsumexp_rows(values: np.ndarray) -> np.ndarray:
    maxima = np.max(values, axis=1)
    return maxima + np.log(np.sum(np.exp(values - maxima[:, None]), axis=1))


def _no_closed_form(_config: Any, _p_value: float) -> float | None:
    return None


def _build_power(config: Any, alarm_config: Any) -> Any:
    from nonconform.martingales import PowerMartingale

    return PowerMartingale(epsilon=config.epsilon, alarm_config=alarm_config)


def _power_log_e(config: Any, p_value: float) -> float | None:
    if p_value == 0.0:
        return float("inf") if config.epsilon < 1.0 else 0.0
    return float(np.log(config.epsilon) + (config.epsilon - 1.0) * np.log(p_value))


def _simulate_power(config: Any, _paths: int) -> Step:
    epsilon = float(config.epsilon)

    def step(p_values: np.ndarray) -> np.ndarray:
        log_p = np.log(p_values)
        return np.log(epsilon) + (epsilon - 1.0) * log_p

    return step


def _build_simple_mixture(config: Any, alarm_config: Any) -> Any:
    from nonconform.martingales import SimpleMixtureMartingale

    return SimpleMixtureMartingale(
        epsilons=config.epsilons,
        n_grid=config.n_grid,
        min_epsilon=config.min_epsilon,
        alarm_config=alarm_config,
    )


def _simulate_simple_mixture(config: Any, paths: int) -> Step:
    epsilons = (
        np.asarray(config.epsilons, dtype=float)
        if config.epsilons is not None
        else np.linspace(float(config.min_epsilon), 1.0, int(config.n_grid))
    )
    log_capitals = np.zeros((paths, len(epsilons)))
    previous_log_mixture = np.zeros(paths)

    def step(p_values: np.ndarray) -> np.ndarray:
        nonlocal log_capitals, previous_log_mixture
        log_p = np.log(p_values)[:, None]
        log_capitals += np.log(epsilons) + (epsilons - 1.0) * log_p
        current_log_mixture = _logsumexp_rows(log_capitals) - np.log(len(epsilons))
        log_increment = current_log_mixture - previous_log_mixture
        previous_log_mixture = current_log_mixture
        return log_increment

    return step


def _build_simple_jumper(config: Any, alarm_config: Any) -> Any:
    from nonconform.martingales import SimpleJumperMartingale

    return SimpleJumperMartingale(jump=config.jump, alarm_config=alarm_config)


def _simulate_simple_jumper(config: Any, paths: int) -> Step:
    jump = float(config.jump)
    epsilons = np.asarray([-1.0, 0.0, 1.0])
    log_components = np.full((paths, 3), np.log(1.0 / 3.0))
    log_stay = float("-inf") if jump == 1.0 else float(np.log1p(-jump))
    log_jump = float(np.log(jump / 3.0))

    def step(p_values: np.ndarray) -> np.ndarray:
        nonlocal log_components
        previous_log_capital = _logsumexp_rows(log_components)
        log_components = np.logaddexp(
            log_stay + log_components,
            log_jump + previous_log_capital[:, None],
        )
        betting_terms = 1.0 + epsilons * (p_values[:, None] - 0.5)
        log_components += np.log(betting_terms)
        current_log_capital = _logsumexp_rows(log_components)
        return current_log_capital - previous_log_capital

    return step


BETTING_FUNCTIONS: dict[str, BettingFunction] = {
    "power": BettingFunction(_build_power, _power_log_e, _simulate_power),
    "simple_mixture": BettingFunction(
        _build_simple_mixture, _no_closed_form, _simulate_simple_mixture
    ),
    "simple_jumper": BettingFunction(
        _build_simple_jumper, _no_closed_form, _simulate_simple_jumper
    ),
}


def betting_function(name: str) -> BettingFunction:
    try:
        return BETTING_FUNCTIONS[name]
    except KeyError:
        raise ValueError(f"Unsupported betting function: {name}") from None


__all__ = ["BETTING_FUNCTIONS", "BettingFunction", "betting_function"]
