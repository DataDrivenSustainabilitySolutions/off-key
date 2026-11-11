"""Prepare steps: deterministic work that runs once per observation, before learning.

Most steps map every feature they use to one value. A feature's state is plain
data, a count or a window of past values, and advancing it returns a new state
without touching the old one. A runtime can therefore stage a whole
observation and keep or drop it as one, and checkpoints restore the same
history. Aggregate, Formula and Gate work on the whole row instead and keep no
state (pipeline_combine.py). The compiler, the validation API and RADAR read
the steps from here.
"""

import math
from array import array
from bisect import bisect_left, bisect_right, insort
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ..schemas.pipelines import (
    AccumulateParameters,
    AggregateParameters,
    ChangeParameters,
    ConditionParameters,
    ConstantParameters,
    DespikeParameters,
    FormulaParameters,
    GateParameters,
    MathParameters,
    PipelineModel,
    PipelineValidation,
    RangeParameters,
    RollingParameters,
    SetFeatureParameters,
    SmoothParameters,
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
}
PREPARE_COMPONENTS = frozenset(PREPARE_MODELS)
# Steps over the whole row; they keep no state and have output from the start.
ROW_COMPONENTS = frozenset(
    {
        "prepare.aggregate",
        "prepare.formula",
        "prepare.gate",
        "prepare.constant",
        "prepare.condition",
        "prepare.set",
    }
)
# Steps that map each feature they use to one value, through a Kernel.
LANE_COMPONENTS = PREPARE_COMPONENTS - ROW_COMPONENTS
# Past values all Prepare windows hold together, across their features.
MAX_WINDOW_VALUES = 50_000
# Scales a median absolute deviation to the standard deviation of normal data.
MAD_SCALE = 1.4826
REJECTION_REASONS = ("non_finite", "out_of_domain", "out_of_range")
_CHANGE_SUFFIXES = {"difference": "diff", "percent": "pct", "lag": "lag"}
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
    return f"{quantile * 100:.6f}".rstrip("0").rstrip(".").replace(".", "p")


def default_suffix(component: str, params: dict[str, Any]) -> str:
    """Short name of a step's added features, following its settings."""
    match component:
        case "prepare.smooth":
            return f"smooth{_setting(component, params, 'window_size')}"
        case "prepare.despike":
            return "despiked"
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
            function = _setting(component, params, "function")
            return "total" if function == "sum" else f"running_{function}"
        case "prepare.math":
            function = _setting(component, params, "function")
            return "scaled" if function == "linear" else function
        case "prepare.range":
            return "clipped"
    raise ValueError(f"Unsupported prepare step: {component}")


class Kernel:
    """One feature's step. advance returns the next state and leaves the old one."""

    lead = 0
    """Values a feature needs before its first output."""
    window = 0
    """Past values a feature keeps."""

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
                mean = math.fsum(window) / size
                deviations = [item - mean for item in window]
                return math.sqrt(math.sumprod(deviations, deviations) / (size - 1))
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
                return math.sqrt(math.sumprod(window, window) / self.size)
        return self._moment_statistic(window)

    def _moment_statistic(self, window: array) -> float:
        """zscore, skewness or excess kurtosis; 0 for a window of one value."""
        size = self.size
        if window.count(window[0]) == size:
            return 0.0
        mean = math.fsum(window) / size
        deviations = [item - mean for item in window]
        # All three compare deviations with each other, so the largest one
        # can stand for 1 and no power of them overflows or vanishes.
        largest = max(map(abs, deviations))
        unit = [item / largest for item in deviations]
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
    """A constant-size running total or extreme, committed with the observation.

    A total keeps what float addition drops in a second number (Neumaier), so
    a long run does not drift; the output is their sum.
    """

    def __init__(self, function: str):
        self.function = function

    def initial(self) -> State:
        return (False, 0.0, 0.0)

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        seen, previous, carry = _carried(state)
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


def kernel(component: str, params: dict[str, Any]) -> Kernel:
    """The step one node runs on each feature it uses."""
    if component not in LANE_COMPONENTS:
        raise ValueError(f"Unsupported prepare step: {component}")
    model = PREPARE_MODELS[component]
    settings = model.model_validate(params)
    if isinstance(settings, SmoothParameters):
        if settings.method == "exponential":
            return Exponential(settings.window_size)
        return Rolling(settings.window_size, "mean")
    if isinstance(settings, DespikeParameters):
        return Despike(settings.window_size, settings.threshold)
    if isinstance(settings, ChangeParameters):
        return Change(settings.lag, settings.mode)
    if isinstance(settings, RollingParameters):
        return Rolling(settings.window_size, settings.statistic, settings.quantile)
    if isinstance(settings, AccumulateParameters):
        return Accumulate(settings.function)
    if isinstance(settings, MathParameters):
        return Function(settings.function, settings.scale, settings.offset)
    assert isinstance(settings, RangeParameters)
    return Bound(settings.low, settings.high, settings.action)


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
    if _setting("prepare.accumulate", params, "function") != "sum":
        return bounds
    low, high = bounds
    return (
        0.0 if low is not None and low >= 0 else None,
        0.0 if high is not None and high <= 0 else None,
    )


def prepared_bounds(component: str, params: dict[str, Any], bounds: Bounds) -> Bounds:
    """The range of a step's output for inputs within bounds; None is open."""
    low, high = bounds
    result: Bounds = (None, None)
    match component:
        case "prepare.smooth" | "prepare.despike":
            # Means, medians and kept values stay within the input's range.
            result = bounds
        case "prepare.change":
            mode = _setting(component, params, "mode")
            if mode == "lag":
                result = bounds
            elif mode == "difference" and low is not None and high is not None:
                result = (low - high, high - low)
        case "prepare.rolling":
            result = _rolling_bounds(params, bounds)
        case "prepare.accumulate":
            result = _accumulated_bounds(params, bounds)
        case "prepare.math":
            result = _function_bounds(params, bounds)
        case "prepare.range":
            result = _range_bounds(params, bounds)
    return _known(result[0]), _known(result[1])


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
        lead = (
            kernel(node.component, node.params).lead
            if node.component in LANE_COMPONENTS
            else 0
        )
        first_output[identifier] = lead + max(
            first_output[parent] for parent in incoming[identifier]
        )
    return StageSplit(steps, frontier, first_output)


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
    "stage_split",
]
