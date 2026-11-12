"""Prepare steps: deterministic work that runs once per observation, before learning.

Most steps map every feature they use to one value. A feature's state is plain
data, a count or a window of past values, and advancing it returns a new state
without touching the old one. A runtime can therefore stage a whole
observation and keep or drop it as one, and checkpoints restore the same
history. Aggregate, Formula and Gate work on the whole row instead and keep no
state (pipeline_combine.py). A few per-feature steps also read the row: an
Accumulate that starts over and a Hold read a condition, and a Rolling
relation reads the feature it compares with; pipeline_combine.py hands them
that value. A Smooth by time constant reads the seconds since its previous
observation, and a Time features step makes features of the observation's time
(pipeline_time.py). The compiler, the validation API and RADAR read the steps
from here.
"""

import math
from array import array
from bisect import bisect_left, bisect_right, insort
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..schemas.pipelines import (
    AccumulateParameters,
    AggregateParameters,
    CalculateParameters,
    ChangeParameters,
    ConditionParameters,
    ConstantParameters,
    DespikeParameters,
    FormulaParameters,
    GateParameters,
    HoldParameters,
    MathParameters,
    PipelineModel,
    PipelineValidation,
    RangeParameters,
    RelationParameters,
    RollingParameters,
    SetFeatureParameters,
    SmoothParameters,
    TimeParameters,
)

PREPARE_MODELS: dict[str, type[PipelineModel]] = {
    "prepare.smooth": SmoothParameters,
    "prepare.despike": DespikeParameters,
    "prepare.change": ChangeParameters,
    "prepare.rolling": RollingParameters,
    "prepare.math": MathParameters,
    "prepare.range": RangeParameters,
    "prepare.aggregate": AggregateParameters,
    "prepare.formula": FormulaParameters,
    "prepare.gate": GateParameters,
    "prepare.constant": ConstantParameters,
    "prepare.condition": ConditionParameters,
    "prepare.set": SetFeatureParameters,
    "prepare.accumulate": AccumulateParameters,
    "prepare.hold": HoldParameters,
    "prepare.relation": RelationParameters,
    "prepare.calculate": CalculateParameters,
    "prepare.time": TimeParameters,
}
PREPARE_COMPONENTS = frozenset(PREPARE_MODELS)
# Steps over the whole row. They keep no state and have output from the start;
# only a Time features step that adds dt waits for its second observation.
ROW_COMPONENTS = frozenset(
    {
        "prepare.aggregate",
        "prepare.formula",
        "prepare.gate",
        "prepare.constant",
        "prepare.condition",
        "prepare.set",
        "prepare.calculate",
        "prepare.time",
    }
)
# Steps that map each feature they use to one value, through a Kernel.
LANE_COMPONENTS = PREPARE_COMPONENTS - ROW_COMPONENTS
# Past values all Prepare windows hold together, across their features.
MAX_WINDOW_VALUES = 50_000
# Scales a median absolute deviation to the standard deviation of normal data.
MAD_SCALE = 1.4826
REJECTION_REASONS = ("non_finite", "out_of_domain", "out_of_range", "out_of_order")
_CHANGE_SUFFIXES = {"difference": "diff", "percent": "pct", "lag": "lag"}
_FIXED_SUFFIXES = {
    "prepare.despike": "despiked",
    "prepare.range": "clipped",
    "prepare.hold": "held",
}
_ACCUMULATE_SUFFIXES = {
    "sum": "total",
    "min": "running_min",
    "max": "running_max",
    "count": "count",
}
_RELATION_SUFFIXES = {
    "correlation": "corr",
    "covariance": "cov",
    "slope": "beta",
    "residual": "resid",
}
_ORDERED_STATISTICS = frozenset(
    {
        *("median", "min", "max", "range", "quantile", "iqr", "mad"),
        *("robust_zscore", "rank"),
    }
)
# Scales a mean absolute deviation to the standard deviation of normal data.
MEAN_DEVIATION_SCALE = math.sqrt(math.pi / 2)

State = tuple[Any, ...]
Bounds = tuple[float | None, float | None]


class PrepareFailure(ValueError):
    """A value a step cannot turn into a finite one; its observation is skipped."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise PrepareFailure("non_finite", "The result is not a finite number")
    return value


def _setting(component: str, params: dict[str, Any], name: str) -> Any:
    """A normalized setting, or the step's default for a draft that leaves it out."""
    if name in params:
        return params[name]
    return PREPARE_MODELS[component].model_fields[name].default


def _quantile_label(quantile: float) -> str:
    """A quantile as a percentage in suffix characters: 0.9 is 90, 0.999 is 99p9.

    The composer names features the same way (scope.ts), so both round to six
    decimals of a percent.
    """
    return _number_label(quantile * 100)


def _number_label(value: float) -> str:
    """A number in suffix characters, to six decimals: 60 is 60, 2.5 is 2p5."""
    return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", "p")


def default_suffix(component: str, params: dict[str, Any]) -> str:
    """Short name of a step's added features, following its settings."""
    if component in _FIXED_SUFFIXES:
        return _FIXED_SUFFIXES[component]
    match component:
        case "prepare.smooth":
            if reads_time(component, params):
                # Seconds, not observations: smooth60s beside smooth60.
                seconds = _setting(component, params, "time_constant")
                return f"smooth{_number_label(seconds)}s"
            return f"smooth{_setting(component, params, 'window_size')}"
        case "prepare.change":
            mode = _setting(component, params, "mode")
            return f"{_CHANGE_SUFFIXES[mode]}{_setting(component, params, 'lag')}"
        case "prepare.rolling":
            statistic = _setting(component, params, "statistic")
            window = _setting(component, params, "window_size")
            if statistic == "quantile":
                # Two quantiles of one window keep apart: q10_60 and q90_60.
                label = _quantile_label(_setting(component, params, "quantile"))
                return f"q{label}_{window}"
            return f"{statistic}{window}"
        case "prepare.accumulate":
            return _ACCUMULATE_SUFFIXES[_setting(component, params, "function")]
        case "prepare.relation":
            statistic = _setting(component, params, "statistic")
            window = _setting(component, params, "window_size")
            return f"{_RELATION_SUFFIXES[statistic]}{window}"
        case "prepare.math":
            function = _setting(component, params, "function")
            return "scaled" if function == "linear" else function
    raise ValueError(f"Unsupported prepare step: {component}")


def reads_time(component: str, params: dict[str, Any]) -> bool:
    """Whether a step needs the time of each observation it sees."""
    if component == "prepare.smooth":
        return _setting(component, params, "method") == "time_constant"
    return component == "prepare.time"


class Kernel:
    """One feature's step. advance returns the next state and leaves the old one.

    A step that reads more than its feature takes it as further arguments of
    advance: see lane_context in pipeline_combine.py.
    """

    lead = 0
    """Values a feature needs before its first output."""
    window = 0
    """Length of the window of past values a feature keeps."""

    @property
    def held(self) -> int:
        """Past values a feature keeps, which count toward MAX_WINDOW_VALUES."""
        return self.window

    def initial(self) -> State:
        return ()

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        raise NotImplementedError

    def accepts(self, state: State) -> bool:
        """Whether a restored state has this step's shape."""
        return state == ()


def _pushed(values: array, value: float, size: int) -> array:
    """A new window with value appended, dropping the oldest value once full."""
    window = values[1:] if len(values) == size else values[:]
    window.append(value)
    return window


def _reordered(ordered: array, leaving: float | None, value: float) -> array:
    """A new sorted copy of the window after leaving goes and value arrives."""
    ordered = ordered[:]
    if leaving is not None:
        del ordered[bisect_left(ordered, leaving)]
    insort(ordered, value)
    return ordered


def _window_state(state: State, size: int, count: int) -> bool:
    if len(state) != count or not all(
        isinstance(item, array) and item.typecode == "d" for item in state
    ):
        return False
    values = state[0]
    return (
        len(values) <= size
        and all(math.isfinite(item) for item in values)
        and all(list(item) == sorted(values) for item in state[1:])
    )


class Exponential(Kernel):
    """y = y' + alpha (x - y') with alpha = 2 / (n + 1), from the first value on.

    Outputs start once n values have arrived, when the start no longer dominates.
    """

    def __init__(self, span: int):
        self.span = span
        self.alpha = 2 / (span + 1)
        self.lead = span - 1

    def initial(self) -> State:
        return (0, 0.0)

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        count, level = state
        level = _finite(value if count == 0 else level + self.alpha * (value - level))
        count = min(count + 1, self.span)
        return (count, level), level if count == self.span else None

    def accepts(self, state: State) -> bool:
        return (
            len(state) == 2
            and isinstance(state[0], int)
            and 0 <= state[0] <= self.span
            and isinstance(state[1], float)
            and math.isfinite(state[1])
        )


def _held_state(state: State) -> bool:
    """Whether a state is (seen, value), with no value before the first one."""
    return (
        len(state) == 2
        and isinstance(state[0], bool)
        and isinstance(state[1], float)
        and math.isfinite(state[1])
        and (state[0] or state[1] == 0.0)
    )


class Decay(Kernel):
    """y = y' + (1 - exp(-dt / tau)) (x - y'), dt seconds after the value before.

    The filter an exponential average approximates when values arrive evenly:
    a value's weight halves every tau ln 2 seconds, however many values arrive
    meanwhile. It starts from its first value and has output from then on.
    """

    def __init__(self, time_constant: float):
        self.time_constant = time_constant

    def initial(self) -> State:
        return (False, 0.0)

    def advance(
        self, state: State, value: float, elapsed: float | None = None
    ) -> tuple[State, float | None]:
        seen, level = state
        if seen and elapsed is not None:
            weight = -math.expm1(-elapsed / self.time_constant)
            value = level + weight * (value - level)
        level = _finite(value)
        return (True, level), level

    def accepts(self, state: State) -> bool:
        return _held_state(state)


class Rolling(Kernel):
    """A statistic of the last n values, from the n-th value on."""

    def __init__(self, size: int, statistic: str, quantile: float = 0.5):
        self.size = size
        self.statistic = statistic
        self.quantile = quantile
        self.ordered = statistic in _ORDERED_STATISTICS
        self.lead = size - 1
        self.window = size
        if statistic == "slope":
            # Positions centred on the window sum to zero, so the mean of the
            # values drops out of the least-squares slope.
            centre = (size - 1) / 2
            self._positions = array("d", (index - centre for index in range(size)))
            self._spread = size * (size * size - 1) / 12

    def initial(self) -> State:
        return (array("d"), array("d")) if self.ordered else (array("d"),)

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        values = state[0]
        leaving = values[0] if len(values) == self.size else None
        window = _pushed(values, value, self.size)
        new = (
            (window, _reordered(state[1], leaving, value))
            if self.ordered
            else (window,)
        )
        if len(window) < self.size:
            return new, None
        try:
            return new, _finite(self._statistic(window, new[-1]))
        except OverflowError:
            raise PrepareFailure(
                "non_finite", "The result is not a finite number"
            ) from None

    def _statistic(self, window: array, ordered: array) -> float:
        size = self.size
        middle = size // 2
        match self.statistic:
            case "sum":
                return math.fsum(window)
            case "mean":
                return math.fsum(window) / size
            case "std":
                return _root_mean_square(_deviations(window), size - 1)
            case "median":
                if size % 2:
                    return ordered[middle]
                return (ordered[middle - 1] + ordered[middle]) / 2
            case "min":
                return ordered[0]
            case "max":
                return ordered[-1]
            case "range":
                return ordered[-1] - ordered[0]
        return self._extended_statistic(window, ordered)

    def _extended_statistic(self, window: array, ordered: array) -> float:
        match self.statistic:
            case "quantile":
                return _quantile(ordered, self.quantile)
            case "iqr":
                return _quantile(ordered, 0.75) - _quantile(ordered, 0.25)
            case "mad":
                return _median_deviation(ordered, _quantile(ordered, 0.5))
            case "slope":
                return math.sumprod(self._positions, window) / self._spread
            case "rank":
                # Values below the latest one, and half of those equal to it.
                below = bisect_left(ordered, window[-1])
                equal = bisect_right(ordered, window[-1]) - below
                return (below + (equal - 1) / 2) / (self.size - 1)
            case "robust_zscore":
                return _robust_score(window, ordered)
            case "rms":
                # The root lies between the smallest and the largest magnitude,
                # which is the range the compiler passes on; rounding may not.
                root = _root_mean_square(window, self.size)
                return max(root, min(map(abs, window)))
        return self._moment_statistic(window)

    def _moment_statistic(self, window: array) -> float:
        """zscore, skewness or excess kurtosis; 0 for a window of one value."""
        size = self.size
        unit, largest = _unit_deviations(window)
        if largest == 0:
            return 0.0
        second = math.sumprod(unit, unit) / size
        if self.statistic == "zscore":
            score = unit[-1] / math.sqrt(second * size / (size - 1))
        elif self.statistic == "skewness":
            third = math.fsum(item * item * item for item in unit) / size
            score = third / second**1.5
        else:
            squares = [item * item for item in unit]
            score = math.sumprod(squares, squares) / size / second**2 - 3
        # No window exceeds these limits; rounding near a flat window may.
        low, high = _moment_limits(self.statistic, size)
        return min(max(score, low), high)

    def accepts(self, state: State) -> bool:
        return _window_state(state, self.size, 2 if self.ordered else 1)


def _deviations(window) -> list[float]:
    """Each value's distance from the mean of the window; 0 in a flat window.

    The mean of large values that differ little rounds to a value next to
    them, which would move every distance by as much as the values differ.
    Values on one side of 0 are therefore measured from the smallest one
    first, and the mean is taken of what remains.
    """
    low, high = min(window), max(window)
    if low == high:
        return [0.0] * len(window)
    start = low if low > 0 or high < 0 else 0.0
    offsets = [item - start for item in window]
    mean = math.fsum(offsets) / len(offsets)
    return [item - mean for item in offsets]


def _unit_deviations(window) -> tuple[list[float], float]:
    """Deviations from the mean with the largest one as 1, and that largest.

    Whatever compares deviations with each other can use these, and no power
    or product of them overflows or vanishes. A flat window has 0 as its
    largest deviation.
    """
    deviations = _deviations(window)
    largest = max(map(abs, deviations))
    if largest == 0:
        return deviations, 0.0
    return [item / largest for item in deviations], largest


def _root_mean_square(values, divisor: int) -> float:
    """The root of the sum of squares over divisor.

    The largest magnitude stands for 1, so the squares of very large or very
    small values neither overflow nor vanish where their root does not.
    """
    largest = max(map(abs, values))
    if largest == 0:
        return 0.0
    unit = [item / largest for item in values]
    return largest * math.sqrt(math.sumprod(unit, unit) / divisor)


def _quantile(ordered, fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    low = int(position)
    weight = position - low
    if weight == 0:
        return ordered[low]
    return (1 - weight) * ordered[low] + weight * ordered[low + 1]


def _deviation(ordered: array, centre: float, rank: int) -> float:
    """The rank-th smallest distance from centre, counted from 1.

    In a sorted window the rank values nearest to centre lie side by side, so
    a binary search finds where they start and nothing is sorted again.
    """
    low, high = 0, len(ordered) - rank
    while low < high:
        middle = (low + high) // 2
        if centre - ordered[middle] > ordered[middle + rank] - centre:
            low = middle + 1
        else:
            high = middle
    return max(centre - ordered[low], ordered[low + rank - 1] - centre)


def _median_deviation(ordered: array, centre: float) -> float:
    """The median distance from centre, as the median of the sorted distances."""
    size = len(ordered)
    middle = _deviation(ordered, centre, size // 2 + 1)
    if size % 2:
        return middle
    return 0.5 * _deviation(ordered, centre, size // 2) + 0.5 * middle


def _robust_score(window: array, ordered: array) -> float:
    """The latest value's distance from the median in scaled MADs.

    More than half of a window can hold one value, which makes the MAD 0;
    the mean absolute deviation then takes its place, scaled alike, so a
    value that differs still stands out. A window of one value gives 0.
    """
    median = _quantile(ordered, 0.5)
    distance = window[-1] - median
    spread = MAD_SCALE * _median_deviation(ordered, median)
    if spread == 0:
        mean_deviation = math.fsum(abs(item - median) for item in window)
        spread = MEAN_DEVIATION_SCALE * mean_deviation / len(window)
    return distance / spread if spread else 0.0


def _moment_limits(statistic: str, size: int) -> tuple[float, float]:
    """The values a statistic of n values can take, whatever the values."""
    if statistic == "zscore":
        # Samuelson: no value lies more than (n - 1) / sqrt(n) deviations out.
        limit = (size - 1) / math.sqrt(size)
        return -limit, limit
    if statistic == "skewness":
        limit = (size - 2) / math.sqrt(size - 1)
        return -limit, limit
    # Excess kurtosis; a window of one value gives 0, above -2.
    return -2.0, max(size - 5 + 1 / (size - 1), 0.0)


def _carried(state: State) -> State:
    """Checkpoints from before totals kept a carry hold (seen, previous)."""
    return (*state, 0.0) if len(state) == 2 else state


class Accumulate(Kernel):
    """A constant-size running total, extreme or count, committed with the
    observation.

    A total keeps what float addition drops in a second number (Neumaier), so
    a long run does not drift; the output is their sum. An observation that
    resets is the first of a new accumulation.
    """

    def __init__(self, function: str):
        self.function = function

    def initial(self) -> State:
        return (False, 0.0, 0.0)

    def advance(
        self, state: State, value: float, reset: bool = False
    ) -> tuple[State, float | None]:
        seen, previous, carry = self.initial() if reset else _carried(state)
        if self.function == "count":
            return (True, previous + 1.0, 0.0), previous + 1.0
        if not seen:
            return (True, value, 0.0), value
        if self.function != "sum":
            value = (min if self.function == "min" else max)(previous, value)
            return (True, value, 0.0), value
        total = previous + value
        if abs(previous) >= abs(value):
            carry += (previous - total) + value
        else:
            carry += (value - total) + previous
        result = _finite(total + carry)
        return (True, total, carry), result

    def accepts(self, state: State) -> bool:
        state = _carried(state)
        return (
            len(state) == 3
            and isinstance(state[0], bool)
            and all(
                isinstance(item, float) and math.isfinite(item) for item in state[1:]
            )
            and (state[0] or state[1:] == (0.0, 0.0))
            and (self.function == "sum" or state[2] == 0.0)
        )


class Hold(Kernel):
    """The value from the last observation its condition held.

    The first observation is always taken, so the step has output from the
    start and a held value is one the feature really had.
    """

    def initial(self) -> State:
        return (False, 0.0)

    def advance(
        self, state: State, value: float, update: bool = True
    ) -> tuple[State, float | None]:
        if update or not state[0]:
            return (True, value), value
        return state, state[1]

    def accepts(self, state: State) -> bool:
        return _held_state(state)


class Relation(Kernel):
    """How a feature moves with another one over their last n pairs of values.

    Deviations from each window's mean are scaled by the largest one before
    they are multiplied, so no product overflows or vanishes; the scales
    return in the result. A window where either feature is flat has no
    direction: its correlation, covariance and slope are 0.
    """

    def __init__(self, size: int, statistic: str):
        self.size = size
        self.statistic = statistic
        self.lead = size - 1
        self.window = size

    @property
    def held(self) -> int:
        """A window of the feature and one of the feature it is compared with."""
        return 2 * self.window

    def initial(self) -> State:
        return (array("d"), array("d"))

    def advance(
        self, state: State, value: float, other: float | None = None
    ) -> tuple[State, float | None]:
        if other is None:
            raise ValueError("A rolling relation needs the other feature's value")
        values = _pushed(state[0], value, self.size)
        others = _pushed(state[1], other, self.size)
        if len(values) < self.size:
            return (values, others), None
        try:
            return (values, others), _finite(self._statistic(values, others))
        except OverflowError:
            raise PrepareFailure(
                "non_finite", "The result is not a finite number"
            ) from None

    def _statistic(self, values: array, others: array) -> float:
        own, scale = _unit_deviations(values)
        other, other_scale = _unit_deviations(others)
        if not scale or not other_scale:
            # The latest value's distance from a flat fit is its distance from
            # the mean.
            return own[-1] * scale if self.statistic == "residual" else 0.0
        together = math.sumprod(own, other)
        if self.statistic == "correlation":
            spread = math.sqrt(math.sumprod(own, own) * math.sumprod(other, other))
            return min(max(together / spread, -1.0), 1.0)
        if self.statistic == "covariance":
            return together / (self.size - 1) * scale * other_scale
        # The slope in scaled units: at most n, since the largest scaled
        # deviation is 1.
        slope = together / math.sumprod(other, other)
        if self.statistic == "slope":
            return slope * scale / other_scale
        return (own[-1] - slope * other[-1]) * scale

    def accepts(self, state: State) -> bool:
        return (
            len(state) == 2
            and all(isinstance(item, array) and item.typecode == "d" for item in state)
            and len(state[0]) == len(state[1]) <= self.size
            and all(math.isfinite(item) for part in state for item in part)
        )


class Despike(Kernel):
    """Replace a value far from the window median with the median.

    The window holds the last w raw values, the current one included. A value
    more than threshold * 1.4826 * MAD from the median is a spike. An excursion
    longer than half the window moves the median and passes; a flat window,
    MAD 0, replaces nothing.
    """

    def __init__(self, size: int, threshold: float):
        self.size = size
        self.threshold = threshold
        self.lead = size - 1
        self.window = size

    def initial(self) -> State:
        return (array("d"), array("d"))

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        values, ordered = state
        leaving = values[0] if len(values) == self.size else None
        window = _pushed(values, value, self.size)
        ordered = _reordered(ordered, leaving, value)
        if len(window) < self.size:
            return (window, ordered), None
        middle = self.size // 2
        median = ordered[middle]
        spread = _deviation(ordered, median, middle + 1)
        spike = spread > 0 and abs(value - median) > self.threshold * MAD_SCALE * spread
        return (window, ordered), median if spike else value

    def accepts(self, state: State) -> bool:
        return _window_state(state, self.size, 2)


class Change(Kernel):
    """Difference, percent change or the value lag observations back."""

    def __init__(self, lag: int, mode: str):
        self.lag = lag
        self.mode = mode
        self.lead = lag
        self.window = lag

    def initial(self) -> State:
        return (array("d"),)

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        (values,) = state
        window = _pushed(values, value, self.lag)
        if len(values) < self.lag:
            return (window,), None
        reference = values[0]
        if self.mode == "lag":
            return (window,), reference
        if self.mode == "difference":
            return (window,), _finite(value - reference)
        if reference == 0:
            raise PrepareFailure("out_of_domain", "Percent change from 0 is undefined")
        return (window,), _finite(100 * (value - reference) / abs(reference))

    def accepts(self, state: State) -> bool:
        return _window_state(state, self.lag, 1)


class Function(Kernel):
    """log, log1p, sqrt, abs, square or scale * x + offset, with domain checks."""

    def __init__(self, function: str, scale: float, offset: float):
        self.function = function
        self.scale = scale
        self.offset = offset

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        match self.function:
            case "log":
                if value <= 0:
                    raise PrepareFailure(
                        "out_of_domain", f"log needs values above 0, not {value:g}"
                    )
                return state, math.log(value)
            case "log1p":
                if value <= -1:
                    raise PrepareFailure(
                        "out_of_domain",
                        f"log1p needs values above -1, not {value:g}",
                    )
                return state, math.log1p(value)
            case "sqrt":
                if value < 0:
                    raise PrepareFailure(
                        "out_of_domain",
                        f"sqrt needs values of at least 0, not {value:g}",
                    )
                return state, math.sqrt(value)
            case "abs":
                return state, abs(value)
            case "square":
                return state, _finite(value * value)
        return state, _finite(self.scale * value + self.offset)


class Bound(Kernel):
    """Clip values to [low, high], or skip observations outside it."""

    def __init__(self, low: float | None, high: float | None, action: str):
        self.low = low
        self.high = high
        self.action = action

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        below = self.low is not None and value < self.low
        above = self.high is not None and value > self.high
        if not below and not above:
            return state, value
        if self.action == "skip":
            limit = f"below {self.low:g}" if below else f"above {self.high:g}"
            raise PrepareFailure("out_of_range", f"{value:g} is {limit}")
        return state, self.low if below else self.high


def _smoother(settings: SmoothParameters) -> Kernel:
    if settings.method == "exponential":
        return Exponential(settings.window_size)
    if settings.method == "time_constant":
        return Decay(settings.time_constant)
    return Rolling(settings.window_size, "mean")


# The step each kind of settings builds.
_KERNELS: dict[type[PipelineModel], Callable[[Any], Kernel]] = {
    SmoothParameters: _smoother,
    DespikeParameters: lambda item: Despike(item.window_size, item.threshold),
    ChangeParameters: lambda item: Change(item.lag, item.mode),
    RollingParameters: lambda item: Rolling(
        item.window_size, item.statistic, item.quantile
    ),
    AccumulateParameters: lambda item: Accumulate(item.function),
    HoldParameters: lambda _item: Hold(),
    RelationParameters: lambda item: Relation(item.window_size, item.statistic),
    MathParameters: lambda item: Function(item.function, item.scale, item.offset),
    RangeParameters: lambda item: Bound(item.low, item.high, item.action),
}


def kernel(component: str, params: dict[str, Any]) -> Kernel:
    """The step one node runs on each feature it uses."""
    if component not in LANE_COMPONENTS:
        raise ValueError(f"Unsupported prepare step: {component}")
    settings = PREPARE_MODELS[component].model_validate(params)
    return _KERNELS[type(settings)](settings)


def _known(value: float | None) -> float | None:
    return value if value is not None and math.isfinite(value) else None


def _magnitude(bounds: Bounds) -> Bounds:
    """Bounds of |x| for x within bounds."""
    low, high = bounds
    if low is not None and low >= 0:
        return bounds
    if high is not None and high <= 0:
        return -high, None if low is None else -low
    if low is not None and high is not None:
        return 0.0, max(-low, high)
    return 0.0, None


def _function_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    function = _setting("prepare.math", params, "function")
    low, high = bounds
    if function == "linear":
        scale = _setting("prepare.math", params, "scale")
        offset = _setting("prepare.math", params, "offset")
        ends = [None if end is None else scale * end + offset for end in bounds]
        return (ends[0], ends[1]) if scale >= 0 else (ends[1], ends[0])
    if function in {"abs", "square"}:
        smallest, largest = _magnitude(bounds)
        if function == "abs":
            return smallest, largest
        return (
            None if smallest is None else smallest * smallest,
            None if largest is None else largest * largest,
        )
    if function == "sqrt":
        return (
            math.sqrt(max(low, 0.0)) if low is not None else 0.0,
            math.sqrt(high) if high is not None and high >= 0 else None,
        )
    floor, apply = (0.0, math.log) if function == "log" else (-1.0, math.log1p)
    return (
        apply(low) if low is not None and low > floor else None,
        apply(high) if high is not None and high > floor else None,
    )


def _range_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    lower = _setting("prepare.range", params, "low")
    upper = _setting("prepare.range", params, "high")
    low, high = bounds

    def clip(value: float) -> float:
        if lower is not None:
            value = max(value, lower)
        return value if upper is None else min(value, upper)

    if _setting("prepare.range", params, "action") == "clip":
        return (
            lower if low is None else clip(low),
            upper if high is None else clip(high),
        )
    # Skipping keeps only values inside both ranges.
    kept = (
        lower if low is None else low if lower is None else max(low, lower),
        upper if high is None else high if upper is None else min(high, upper),
    )
    if kept[0] is not None and kept[1] is not None and kept[0] > kept[1]:
        return lower, upper
    return kept


def _rolling_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    low, high = bounds
    statistic = _setting("prepare.rolling", params, "statistic")
    if statistic in {"mean", "median", "min", "max", "quantile"}:
        return bounds
    if statistic == "sum":
        size = _setting("prepare.rolling", params, "window_size")
        return (
            None if low is None else low * size,
            None if high is None else high * size,
        )
    if statistic == "slope":
        return (
            (low - high, high - low)
            if low is not None and high is not None
            else (None, None)
        )
    if statistic in {"range", "iqr", "mad"} and low is not None and high is not None:
        return 0.0, high - low
    if statistic in {"zscore", "skewness", "kurtosis"}:
        size = _setting("prepare.rolling", params, "window_size")
        return _moment_limits(statistic, size)
    if statistic == "rank":
        return 0.0, 1.0
    if statistic == "robust_zscore":
        return None, None
    if statistic == "rms":
        return _magnitude(bounds)
    return 0.0, None


def _accumulated_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    function = _setting("prepare.accumulate", params, "function")
    if function == "count":
        return 1.0, None
    if function != "sum":
        return bounds
    low, high = bounds
    return (
        0.0 if low is not None and low >= 0 else None,
        0.0 if high is not None and high <= 0 else None,
    )


def _change_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    low, high = bounds
    mode = _setting("prepare.change", params, "mode")
    if mode == "lag":
        return bounds
    if mode == "difference" and low is not None and high is not None:
        return low - high, high - low
    return None, None


def _relation_bounds(params: dict[str, Any], _bounds: Bounds) -> Bounds:
    if _setting("prepare.relation", params, "statistic") == "correlation":
        return -1.0, 1.0
    return None, None


_BOUNDS: dict[str, Callable[[dict[str, Any], Bounds], Bounds]] = {
    "prepare.change": _change_bounds,
    "prepare.rolling": _rolling_bounds,
    "prepare.accumulate": _accumulated_bounds,
    "prepare.math": _function_bounds,
    "prepare.range": _range_bounds,
    "prepare.relation": _relation_bounds,
}


def prepared_bounds(component: str, params: dict[str, Any], bounds: Bounds) -> Bounds:
    """The range of a step's output for inputs within bounds; None is open."""
    ranged = _BOUNDS.get(component)
    # A step without a rule keeps the input's range: a smoothed, despiked or
    # held value lies within it.
    low, high = bounds if ranged is None else ranged(params, bounds)
    return _known(low), _known(high)


@dataclass(frozen=True)
class StageSplit:
    """Where the Prepare stage ends: the nodes it runs and the ones it hands over."""

    steps: tuple[str, ...]
    """Prepare steps and the routes before them, in compiled order."""
    frontier: tuple[str, ...]
    """The stage's nodes, and the input, whose features the learned stage reads."""
    first_output: dict[str, int]
    """The observation, counted from 1, on which each node first has output."""

    def columns(self, names: dict[str, list[str]]) -> list[str]:
        """The learned stage's input columns: node id and feature name."""
        return [f"{node}.{name}" for node in self.frontier for name in names[node]]

    @property
    def required(self) -> int:
        """Observations until the first prepared row reaches the learned stage."""
        return max(self.first_output[node] for node in self.frontier)


def stage_split(compiled: PipelineValidation) -> StageSplit | None:
    """Cut a compiled graph between the Prepare stage and the learned stage."""
    nodes = {node.id: node for node in compiled.definition.nodes}
    prepare = [
        key for key, node in nodes.items() if node.component in PREPARE_COMPONENTS
    ]
    if not prepare:
        return None
    incoming = compiled.incoming
    source = compiled.source_id
    members: set[str] = set()
    pending = list(prepare)
    while pending:
        identifier = pending.pop()
        if identifier != source and identifier not in members:
            members.add(identifier)
            pending.extend(incoming[identifier])
    consumers: dict[str, list[str]] = defaultdict(list)
    for edge in compiled.definition.edges:
        consumers[edge.source].append(edge.target)
    steps = tuple(key for key in compiled.order if key in members)
    frontier = tuple(
        key
        for key in compiled.order
        if (key in members or key == source)
        and any(target not in members for target in consumers[key])
    )
    first_output = {source: 1}
    for identifier in steps:
        node = nodes[identifier]
        first_output[identifier] = step_lead(node.component, node.params) + max(
            first_output[parent] for parent in incoming[identifier]
        )
    return StageSplit(steps, frontier, first_output)


def step_lead(component: str, params: dict[str, Any]) -> int:
    """Observations a step sees before the one that gives its first output."""
    if component in LANE_COMPONENTS:
        return kernel(component, params).lead
    if component == "prepare.time":
        # No observation comes before the first to measure dt from.
        return int(_setting(component, params, "elapsed"))
    return 0


__all__ = [
    "LANE_COMPONENTS",
    "MAX_WINDOW_VALUES",
    "PREPARE_COMPONENTS",
    "PREPARE_MODELS",
    "REJECTION_REASONS",
    "ROW_COMPONENTS",
    "Kernel",
    "PrepareFailure",
    "StageSplit",
    "default_suffix",
    "kernel",
    "prepared_bounds",
    "reads_time",
    "stage_split",
    "step_lead",
]
