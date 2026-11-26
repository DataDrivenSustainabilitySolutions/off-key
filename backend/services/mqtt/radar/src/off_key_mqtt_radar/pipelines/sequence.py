"""Prepare steps that run on aberrant's sequence transformers.

off_key_core describes every Prepare step. Smoothing, Despike, Change, Lags
in observations and Rolling compute what aberrant's sequence transformers
compute, so RADAR runs them there and keeps each feature's state itself. A
step withholds its output until the feature has seen its lead, as every
Prepare step does.
"""

from __future__ import annotations

from typing import Any

from aberrant.exceptions import ValidationError
from aberrant.transform import (
    Despike,
    Difference,
    ExponentialSmoother,
    Lags,
    RollingStatistic,
)
from off_key_core.models import pipeline_prepare as described
from off_key_core.models.pipeline_prepare import Kernel, PrepareFailure, State, kernel

Transformer = Despike | Difference | ExponentialSmoother | Lags | RollingStatistic


class SequenceStep(Kernel):
    """A described step that an aberrant sequence transformer computes.

    A feature's state is the values it has seen, up to lead + 1, and the
    transformer's own state.
    """

    def __init__(self, description: Kernel, transformer: Transformer):
        self.lead = description.lead
        self.window = description.window
        self.width = description.width
        self.several = description.several
        self.transformer = transformer

    def initial(self) -> State:
        return (0, self.transformer.initial_state())

    def advance(self, state: State, value: float) -> tuple[State, Any]:
        seen, inner = state
        try:
            inner, outputs = self.transformer.step(inner, value)
        except ValidationError as error:
            if "finite" in str(error):
                raise PrepareFailure(
                    "non_finite", "The result is not a finite number"
                ) from None
            raise PrepareFailure("out_of_domain", str(error)) from None
        seen = min(seen + 1, self.lead + 1)
        if seen <= self.lead:
            return (seen, inner), None
        return (seen, inner), outputs if self.several else outputs[0]

    def accepts(self, state: State) -> bool:
        return (
            len(state) == 2
            and type(state[0]) is int
            and 0 <= state[0] <= self.lead + 1
            and self.transformer.valid_state(state[1])
        )


def _transformer(description: Kernel) -> Transformer | None:
    match description:
        case described.Exponential():
            return ExponentialSmoother(span=description.span)
        case described.Rolling():
            return RollingStatistic(
                window_size=description.size,
                statistic=description.statistic,
                quantile=description.quantile,
            )
        case described.Despike():
            return Despike(
                window_size=description.size, threshold=description.threshold
            )
        case described.Change(mode="lag"):
            return Lags(lags=[description.lag])
        case described.Change():
            return Difference(lag=description.lag, kind=description.mode)
        case described.Lags():
            return Lags(lags=list(description.lags))
    return None


def runnable(component: str, params: dict[str, Any]) -> Kernel:
    """The step one node runs on each feature it uses."""
    description = kernel(component, params)
    transformer = _transformer(description)
    if transformer is None:
        return description
    return SequenceStep(description, transformer)


__all__ = ["SequenceStep", "runnable"]
