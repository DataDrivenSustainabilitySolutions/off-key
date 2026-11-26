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
from here. Smoothing over observations, Despike, Change, Lags in observations
and Rolling are described here and computed by aberrant's sequence
transformers in RADAR.
"""

import math
from array import array
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from ..schemas.pipelines import (
    DESEASON_CYCLES,
    LAG_UNITS,
    AccumulateParameters,
    AggregateParameters,
    CalculateParameters,
    ChangeParameters,
    ConditionParameters,
    ConstantParameters,
    CusumParameters,
    DeseasonParameters,
    DespikeParameters,
    FormulaParameters,
    GateParameters,
    HoldParameters,
    LagsParameters,
    MathParameters,
    MuteParameters,
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
    "prepare.lags": LagsParameters,
    "prepare.deseason": DeseasonParameters,
    "prepare.cusum": CusumParameters,
    "prepare.rolling": RollingParameters,
    "prepare.math": MathParameters,
    "prepare.range": RangeParameters,
    "prepare.aggregate": AggregateParameters,
    "prepare.formula": FormulaParameters,
    "prepare.gate": GateParameters,
    "prepare.mute": MuteParameters,
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
        "prepare.mute",
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
    # Each lag follows: power_lag24.
    "prepare.lags": "lag",
    "prepare.deseason": "deseasoned",
    "prepare.cusum": "cusum",
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
# Scales a mean absolute deviation to the standard deviation of normal data.
MEAN_DEVIATION_SCALE = math.sqrt(math.pi / 2)

State = tuple[Any, ...]
Bounds = tuple[float | None, float | None]


class PrepareFailure(ValueError):
    """A value a step cannot turn into a finite one; its observation is skipped."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def finite_result(value: float) -> float:
    """``value``, or a ``non_finite`` failure when a computation overflowed."""
    if not math.isfinite(value):
        raise PrepareFailure("non_finite", "The result is not a finite number")
    return value


def _setting(component: str, params: dict[str, Any], name: str) -> Any:
    """A normalized setting, or the step's default for a draft that leaves it out."""
    if name in params:
        return params[name]
    return (
        PREPARE_MODELS[component]
        .model_fields[name]
        .get_default(call_default_factory=True)
    )


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


def output_suffixes(
    component: str, params: dict[str, Any], suffix: str
) -> tuple[str, ...]:
    """What each of a feature's added features appends to its name, in output
    order: the suffix itself, or for Lags the suffix and each lag."""
    if component == "prepare.lags":
        lags = sorted(_setting(component, params, "lags"))
        unit = LAG_UNITS.get(_setting(component, params, "unit"))
        ending = "" if unit is None else unit[1]
        return tuple(f"{suffix}{lag}{ending}" for lag in lags)
    return (suffix,)


def reads_time(component: str, params: dict[str, Any]) -> bool:
    """Whether a step needs the time of each observation it sees."""
    if component == "prepare.smooth":
        return _setting(component, params, "method") == "time_constant"
    if component == "prepare.lags":
        return _setting(component, params, "unit") != "observations"
    return component in ("prepare.time", "prepare.deseason")


class Kernel:
    """One feature's step. advance returns the next state and leaves the old one.

    A step that reads more than its feature takes it as further arguments of
    advance: see lane_context in pipeline_combine.py.
    """

    lead = 0
    """Values a feature needs before its first output."""
    window = 0
    """Length of the window of past values a feature keeps."""
    width = 1
    """Values a feature gives per observation."""
    several = False
    """Whether advance returns its values as a tuple, in the order of
    output_suffixes, rather than one value: Lags do, even with one lag."""

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

    def waiting(self, state: State) -> bool:
        """Whether a feature still waits for its first output after its lead,
        as a step that warms up over time rather than observations does."""
        return False


def _pushed(values: array, value: float, size: int) -> array:
    """A new window with value appended, dropping the oldest value once full."""
    window = values[1:] if len(values) == size else values[:]
    window.append(value)
    return window


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

    Outputs start once n values have arrived, when the start no longer
    dominates. RADAR runs it on aberrant.
    """

    def __init__(self, span: int):
        self.span = span
        self.lead = span - 1


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
        level = finite_result(value)
        return (True, level), level

    def accepts(self, state: State) -> bool:
        return _held_state(state)


class Rolling(Kernel):
    """A statistic of the last n values, from the n-th value on.

    RADAR runs it on aberrant.
    """

    def __init__(self, size: int, statistic: str, quantile: float = 0.5):
        self.size = size
        self.statistic = statistic
        self.quantile = quantile
        self.lead = size - 1
        self.window = size


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
        result = finite_result(total + carry)
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
            return (values, others), finite_result(self._statistic(values, others))
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
    MAD 0, replaces nothing. RADAR runs it on aberrant.
    """

    def __init__(self, size: int, threshold: float):
        self.size = size
        self.threshold = threshold
        self.lead = size - 1
        self.window = size


class Change(Kernel):
    """Difference, percent change or the value lag observations back.

    RADAR runs it on aberrant.
    """

    def __init__(self, lag: int, mode: str):
        self.lag = lag
        self.mode = mode
        self.lead = lag
        self.window = lag


class Lags(Kernel):
    """The values several observations back, one output per lag, ascending.

    RADAR runs it on aberrant.
    """

    def __init__(self, lags: list[int]):
        self.lags = tuple(sorted(lags))
        self.width = len(self.lags)
        self.several = True
        self.lead = self.lags[-1]
        self.window = self.lags[-1]


# How closely a lag in time finds its value: within this share of the lag.
LAG_PRECISION = 0.01
# The shortest spacing of observations the memory of a time lag is sized for.
LAG_SPACING = 0.1


class TimeLags(Kernel):
    """The last values at or before several times back, one output per lag.

    The state holds past observations, thinned with their age: one between
    two others leaves once those two lie closer together than 1% of the
    newer one's age. A lag then finds an observation within 1% of itself of
    the time it asks for, and the memory grows with the log of the longest
    lag rather than with the observations it spans. The step has output once
    an observation lies the longest lag back.
    """

    def __init__(self, seconds: list[float]):
        self.seconds = tuple(sorted(seconds))
        self.width = len(self.seconds)
        self.several = True
        longest = self.seconds[-1]
        # Ages below 100 spacings keep every observation; beyond, the spacing
        # grows by 1% of the age, which takes 100 ln(ratio) points.
        self.window = (
            math.ceil(
                (1 + math.log(max(longest / (LAG_SPACING / LAG_PRECISION), 1)))
                / LAG_PRECISION
            )
            + 2
        )

    @property
    def held(self) -> int:
        """A time and a value per point."""
        return 2 * self.window

    def initial(self) -> State:
        return (array("d"), array("d"))

    def advance(
        self, state: State, value: float, now: float | None = None
    ) -> tuple[State, Any]:
        """The next state and a value per lag, or None until the longest is covered."""
        if now is None:
            raise ValueError("A lag in time needs the time of each observation")
        times, values = state
        oldest = now - self.seconds[-1]
        result = None
        if times and times[0] <= oldest:
            result = tuple(
                values[bisect_right(times, now - lag) - 1] for lag in self.seconds
            )
        return self._thinned(times, values, now, value), result

    def _thinned(self, times: array, values: array, now: float, value: float):
        kept_times = array("d", [now])
        kept_values = array("d", [value])
        # From the newest back: a point leaves where its neighbours lie close
        # enough for its age, or where a newer one already lies past the
        # longest lag.
        newer = now
        longest = self.seconds[-1]
        for index in range(len(times) - 1, -1, -1):
            time = times[index]
            if now - newer >= longest:
                break
            older = times[index - 1] if index else None
            if older is not None and newer - older <= LAG_PRECISION * (now - newer):
                continue
            kept_times.append(time)
            kept_values.append(values[index])
            newer = time
        kept_times.reverse()
        kept_values.reverse()
        return (kept_times, kept_values)

    def accepts(self, state: State) -> bool:
        if len(state) != 2 or not all(
            isinstance(item, array) and item.typecode == "d" for item in state
        ):
            return False
        times, values = state
        return (
            len(times) == len(values)
            and all(math.isfinite(item) for part in state for item in part)
            and all(left < right for left, right in pairwise(times))
        )

    def waiting(self, state: State) -> bool:
        times = state[0]
        return not times or times[-1] - times[0] < self.seconds[-1]


class Deseason(Kernel):
    """A value less the usual level of its slot of the day or week.

    Each slot keeps a level and a spread. They average the slot's values until
    they hold memory cycles' worth, then forget the oldest at that pace. A
    value further than four spreads from its level moves them as if it lay at
    four, so one unusual day leaves the profile where it was. The level is
    read before the value updates it, and the step has output once a whole
    cycle has passed and the slot has a level.

    With trend, as in STL, the slots learn the value less a trend rather than
    the value itself, and the output is the value less both. The trend is the
    mean of the values so far during the first cycle, then a moving average
    of the value less its slot's level, centred on the levels' mean as STL
    centres its seasonal part, that forgets over one cycle, so the pattern of
    the day does not leak into it. The same four spreads bound how far one
    value moves it.
    """

    def __init__(
        self, cycle: int, slot: int, memory: int, zone: tzinfo, trend: bool = False
    ):
        self.cycle = float(cycle)
        self.slot = slot
        self.slots = cycle // slot
        self.memory = memory
        self.zone = zone
        self.trend = trend
        self.window = 3 * self.slots + 3

    def initial(self) -> State:
        empty = array("d", bytes(8 * self.slots))
        return (array("d"), empty, empty[:], empty[:])

    def _index(self, now: float) -> int:
        try:
            moment = datetime.fromtimestamp(now, self.zone)
        except (OverflowError, OSError, ValueError) as error:
            raise PrepareFailure(
                "out_of_range", "The observation's time is outside the calendar"
            ) from error
        seconds = moment.hour * 3600 + moment.minute * 60 + moment.second
        if self.cycle > 86_400:
            seconds += moment.weekday() * 86_400
        return min(int(seconds // self.slot), self.slots - 1)

    def advance(
        self, state: State, value: float, now: float | None = None
    ) -> tuple[State, float | None]:
        if now is None:
            raise ValueError("Taking out a daily pattern needs each observation's time")
        start, levels, spreads, counts = state
        first, last = (start[0], start[1]) if start else (now, now)
        if start and now < last:
            raise PrepareFailure("out_of_order", "The observation is not newer")
        index = self._index(now)
        level, spread, count = levels[index], spreads[index], counts[index]
        # Without trend the base stays 0 and the slots learn the value itself.
        base = (start[2] if start else value) if self.trend else 0.0
        detrended = value - base
        ready = count > 0 and now - first >= self.cycle
        result = detrended - level if ready else None
        # The slot's observations per cycle so far set how many make memory
        # cycles, so a slot forgets at the same pace however often it reports.
        cycles = max((now - first) / self.cycle, 1.0)
        horizon = self.memory * max(count / cycles, 1.0)
        weight = 1.0 / min(count + 1.0, horizon)
        limit = 4 * spread if count >= 5 and spread > 0 else math.inf
        deviation = min(max(detrended - level, -limit), limit) if count else 0.0
        if self.trend and start:
            if now - first < self.cycle:
                pace = 1.0 / (sum(counts) + 1.0)
            else:
                pace = -math.expm1(-(now - last) / self.cycle)
            # As in STL the seasonal part is centred on 0: the mean of the
            # levels belongs to the trend, or the trend's lag behind a drift
            # would settle in the levels and the trend would stop moving.
            known = [item for item, seen in zip(levels, counts, strict=True) if seen]
            centre = sum(known) / len(known) if known else 0.0
            # The value less the trend and the centred season; the clip
            # bounds the part the levels do not explain.
            base += pace * (deviation + centre if count else detrended)
        levels, spreads, counts = levels[:], spreads[:], counts[:]
        levels[index] = level + weight * deviation if count else detrended
        spreads[index] = spread + weight * (abs(deviation) - spread)
        counts[index] = count + 1.0
        return (array("d", [first, now, base]), levels, spreads, counts), result

    def accepts(self, state: State) -> bool:
        if len(state) != 4 or not all(
            isinstance(item, array) and item.typecode == "d" for item in state
        ):
            return False
        start, *slots = state
        return (
            len(start) in (0, 3)
            and all(len(item) == self.slots for item in slots)
            and all(math.isfinite(item) for part in state for item in part)
        )

    def waiting(self, state: State) -> bool:
        start = state[0]
        return not start or start[1] - start[0] < self.cycle


class Cusum(Kernel):
    """Two-sided cumulative sum of how far values lie from their usual level.

    The usual level and spread are a mean and mean absolute deviation, learned
    over the first window values and then followed at that pace, but only
    while the sum stays below half of reset_at: during a shift they hold, so
    the shift is not absorbed before it is found. Each value adds its distance
    from the level, in spreads, less the slack, to the upward or the downward
    sum; a sum never falls below 0. The output is the larger sum. Once it
    passes reset_at, both sums start over and the level moves to the recent
    level, a mean over a tenth of the window, so a lasting shift gives one
    rise rather than a sum that grows without end.
    """

    def __init__(self, window: int, slack: float, reset_at: float):
        self.size = window
        self.recent = max(window // 10, 5)
        self.slack = slack
        self.reset_at = reset_at
        self.lead = window
        # Level, spread, recent level, upward and downward sums, values seen.
        self.window = 6

    def initial(self) -> State:
        return (array("d", [0.0] * 6),)

    def advance(self, state: State, value: float) -> tuple[State, float | None]:
        level, spread, recent, up, down, seen = state[0]
        seen += 1
        recent += (value - recent) / min(seen, self.recent)
        if seen <= self.size:
            # The first window: a plain mean and mean absolute deviation.
            level += (value - level) / seen
            spread += (abs(value - level) - spread) / seen
            return (array("d", [level, spread, recent, up, down, seen]),), None
        scale = spread * MEAN_DEVIATION_SCALE
        distance = (value - level) / scale if scale > 0 else 0.0
        up = max(0.0, up + distance - self.slack)
        down = max(0.0, down - distance - self.slack)
        result = max(up, down)
        if result > self.reset_at:
            level, up, down = recent, 0.0, 0.0
        elif result <= self.reset_at / 2:
            level += (value - level) / self.size
            spread += (abs(value - level) - spread) / self.size
        return (array("d", [level, spread, recent, up, down, seen]),), result

    def accepts(self, state: State) -> bool:
        return (
            len(state) == 1
            and isinstance(state[0], array)
            and state[0].typecode == "d"
            and len(state[0]) == 6
            and all(math.isfinite(item) for item in state[0])
            and state[0][1] >= 0
        )


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
                return state, finite_result(value * value)
        return state, finite_result(self.scale * value + self.offset)


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


def _lags(settings: LagsParameters) -> Kernel:
    if settings.unit == "observations":
        return Lags(settings.lags)
    seconds = LAG_UNITS[settings.unit][0]
    return TimeLags([lag * seconds for lag in settings.lags])


# The step each kind of settings builds.
_KERNELS: dict[type[PipelineModel], Callable[[Any], Kernel]] = {
    SmoothParameters: _smoother,
    DespikeParameters: lambda item: Despike(item.window_size, item.threshold),
    ChangeParameters: lambda item: Change(item.lag, item.mode),
    LagsParameters: _lags,
    CusumParameters: lambda item: Cusum(item.window_size, item.slack, item.reset_at),
    DeseasonParameters: lambda item: Deseason(
        DESEASON_CYCLES[item.cycle],
        60 * item.slot_minutes,
        item.memory,
        UTC if item.timezone == "UTC" else ZoneInfo(item.timezone),
        item.trend,
    ),
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


def _deseasoned_bounds(params: dict[str, Any], bounds: Bounds) -> Bounds:
    """A value less a level that lies within the same range.

    A trend learns from values less their level, which can leave the range, so
    with trend there is no bound.
    """
    low, high = bounds
    if params.get("trend") or low is None or high is None:
        return None, None
    return low - high, high - low


_BOUNDS: dict[str, Callable[[dict[str, Any], Bounds], Bounds]] = {
    "prepare.change": _change_bounds,
    "prepare.deseason": _deseasoned_bounds,
    "prepare.cusum": lambda _params, _bounds: (0.0, None),
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
    "output_suffixes",
    "prepared_bounds",
    "reads_time",
    "stage_split",
    "step_lead",
]
