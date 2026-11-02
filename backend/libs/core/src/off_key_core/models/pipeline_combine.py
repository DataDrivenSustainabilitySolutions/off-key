"""Aggregate, Formula and Gate: Prepare steps over the whole row.

They keep no state and have output from the first observation. Aggregate and
Formula compute one feature, which follows the features they keep; Gate holds
back the observations its condition rejects. The compiler names and bounds
their features here, checks the values Prepare steps will skip, and RADAR runs
the steps built here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..schemas.pipelines import FeatureDescription
from .pipeline_formula import (
    Expression,
    FormulaError,
    analyze,
    domain_issue,
    evaluator,
    interval,
    parse,
)
from .pipeline_prepare import PREPARE_MODELS, Bounds, PrepareFailure
from .pipeline_scope import ScopeError, adds, step_scope

Row = Mapping[str, float]
Columns = list[FeatureDescription]
_DEFAULT_NAMES = {"prepare.formula": "formula"}


def _setting(component: str, params: Mapping[str, Any], name: str) -> Any:
    if name in params:
        return params[name]
    return PREPARE_MODELS[component].model_fields[name].default


def combined_name(component: str, params: Mapping[str, Any]) -> str:
    """The computed feature's name: the chosen one, formula, or the function."""
    return (
        params.get("name")
        or _DEFAULT_NAMES.get(component)
        or _setting(component, params, "function")
    )


def expression(component: str, params: Mapping[str, Any]) -> Expression:
    """A Formula's expression or a Gate's condition; errors name their setting."""
    parameter = "condition" if component == "prepare.gate" else "expression"
    try:
        return parse(params[parameter], condition=component == "prepare.gate")
    except FormulaError as error:
        error.parameter = parameter
        raise


def _checked(component: str, params: Mapping[str, Any], names: Sequence[str]):
    parsed = expression(component, params)
    try:
        parsed.check_names(names)
    except FormulaError as error:
        error.parameter = parsed_parameter(component)
        raise
    return parsed


def parsed_parameter(component: str) -> str:
    return "condition" if component == "prepare.gate" else "expression"


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise PrepareFailure("non_finite", "The result is not a finite number")
    return value


def _combined(row: Row, removed: Sequence[str], name: str, value: float):
    """Kept features in their order, then the computed one."""
    gone = set(removed)
    output = {key: item for key, item in row.items() if key not in gone}
    output[name] = value
    return output


def _aggregate(function: str, values: list[float]) -> float:
    try:
        match function:
            case "mean":
                return _finite(math.fsum(values) / len(values))
            case "sum":
                return _finite(math.fsum(values))
            case "min":
                return min(values)
            case "max":
                return max(values)
            case "range":
                return _finite(max(values) - min(values))
        mean = math.fsum(values) / len(values)
        deviations = [value - mean for value in values]
        spread = math.sumprod(deviations, deviations) / (len(values) - 1)
        return _finite(math.sqrt(spread))
    except OverflowError:
        raise PrepareFailure(
            "non_finite", "The result is not a finite number"
        ) from None


@dataclass(frozen=True)
class Aggregate:
    """Mean, sum, min, max, standard deviation or range across features."""

    selected: tuple[str, ...]
    function: str
    name: str
    add: bool

    def apply(self, row: Row) -> dict[str, float]:
        value = _aggregate(self.function, [row[name] for name in self.selected])
        return _combined(row, () if self.add else self.selected, self.name, value)


@dataclass(frozen=True)
class Formula:
    """One feature computed by an expression over the row."""

    expression: Expression
    evaluate: Callable[[Row], Any]
    name: str
    add: bool

    def apply(self, row: Row) -> dict[str, float]:
        value = float(self.evaluate(row))
        removed = () if self.add else self.expression.names
        return _combined(row, removed, self.name, value)


@dataclass(frozen=True)
class Gate:
    """Lets an observation on when its condition holds; features pass unchanged."""

    expression: Expression
    evaluate: Callable[[Row], Any]

    def opens(self, row: Row) -> bool:
        return bool(self.evaluate(row))


RowStep = Aggregate | Formula | Gate


def row_step(
    component: str, params: Mapping[str, Any], inputs: Sequence[str]
) -> RowStep:
    """The step a node runs on each observation, given the features reaching it."""
    if component == "prepare.aggregate":
        scope = step_scope(component, dict(params), inputs)
        return Aggregate(
            scope.selected,
            _setting(component, params, "function"),
            combined_name(component, params),
            scope.add,
        )
    parsed = _checked(component, params, inputs)
    if component == "prepare.gate":
        return Gate(parsed, evaluator(parsed))
    return Formula(
        parsed,
        evaluator(parsed),
        combined_name(component, params),
        adds(component, dict(params)),
    )


def _bounds(columns: Columns) -> dict[str, Bounds]:
    return {item.name: (item.minimum, item.maximum) for item in columns}


def _hull(bounds: list[Bounds], function: str) -> Bounds:
    lows = [low for low, _ in bounds]
    highs = [high for _, high in bounds]
    if function in {"std", "range"}:
        if None in lows or None in highs:
            return 0.0, None
        width = max(h for h in highs if h is not None) - min(
            low for low in lows if low is not None
        )
        return 0.0, width
    if function == "sum":
        return (
            None if None in lows else math.fsum(low for low in lows if low is not None),
            None
            if None in highs
            else math.fsum(high for high in highs if high is not None),
        )
    known_lows = [low for low in lows if low is not None]
    known_highs = [high for high in highs if high is not None]
    if function == "min":
        # The minimum is at most the smallest high and at least the smallest low.
        return (
            None if None in lows else min(known_lows),
            min(known_highs) if known_highs else None,
        )
    if function == "max":
        return (
            max(known_lows) if known_lows else None,
            None if None in highs else max(known_highs),
        )
    return (
        None if None in lows else min(known_lows),
        None if None in highs else max(known_highs),
    )


def combined_columns(
    component: str, params: Mapping[str, Any], columns: Columns
) -> Columns:
    """The features after an Aggregate, Formula or Gate."""
    names = [item.name for item in columns]
    if component == "prepare.gate":
        _checked(component, params, names)
        return columns
    name = combined_name(component, params)
    if component == "prepare.aggregate":
        scope = step_scope(component, dict(params), names)
        if len(scope.selected) < 2:
            raise ScopeError("Aggregate needs at least 2 features.", "apply_to")
        used = list(scope.selected)
        function = _setting(component, params, "function")
        low, high = _hull(
            [(item.minimum, item.maximum) for item in columns if item.name in used],
            function,
        )
        add = scope.add
    else:
        parsed = _checked(component, params, names)
        used = list(parsed.names)
        analysis = analyze(parsed, _bounds(columns))
        low, high = analysis.low, analysis.high
        add = adds(component, dict(params))
    kept = [item for item in columns if add or item.name not in used]
    if any(item.name == name for item in kept):
        raise ScopeError(f"{name} already exists. Choose another name.", "name")
    lineage = sorted(
        {slot for item in columns if item.name in used for slot in item.slots}
    )
    return [
        *kept,
        FeatureDescription(
            name=name, slots=lineage, minimum=low, maximum=high, raw=False
        ),
    ]


@dataclass(frozen=True)
class ValueIssue:
    """Values a step will skip, found from the ranges of its features."""

    severity: str
    message: str
    parameter: str


def value_issues(
    component: str,
    params: Mapping[str, Any],
    columns: Columns,
    labels: Mapping[str, str],
) -> list[ValueIssue]:
    """Warn where some observations will be skipped, refuse where all would be."""
    if component in {"prepare.formula", "prepare.gate"}:
        return _expression_issues(component, params, columns, labels)
    names = [item.name for item in columns]
    scope = step_scope(component, dict(params), names)
    ranges = {item.name: interval((item.minimum, item.maximum)) for item in columns}
    issues: list[ValueIssue] = []
    if component == "prepare.math":
        function = _setting(component, params, "function")
        if function not in {"log", "log1p", "sqrt"}:
            return issues
        for name in scope.selected:
            warning, error = domain_issue(
                function, ranges[name], labels.get(name, name)
            )
            if error:
                issues.append(ValueIssue("error", error, "function"))
            elif warning:
                issues.append(ValueIssue("warning", warning, "function"))
    elif (
        component == "prepare.change"
        and _setting(component, params, "mode") == "percent"
    ):
        for name in scope.selected:
            low, high = ranges[name]
            if low <= 0 <= high:
                issues.append(
                    ValueIssue(
                        "warning",
                        f"Percent change of {labels.get(name, name)}: observations "
                        "compared with a 0 are skipped.",
                        "mode",
                    )
                )
    return issues


def _expression_issues(
    component: str,
    params: Mapping[str, Any],
    columns: Columns,
    labels: Mapping[str, str],
) -> list[ValueIssue]:
    parameter = parsed_parameter(component)
    parsed = expression(component, params)
    analysis = analyze(parsed, _bounds(columns), labels)
    issues = [ValueIssue("error", text, parameter) for text in analysis.errors]
    issues += [ValueIssue("warning", text, parameter) for text in analysis.warnings]
    if component == "prepare.gate" and analysis.truth is False:
        issues.append(
            ValueIssue(
                "error",
                "The condition is never true, so no observation would reach "
                "the detector.",
                parameter,
            )
        )
    elif component == "prepare.gate" and analysis.truth:
        issues.append(
            ValueIssue(
                "warning",
                "The condition is always true, so the gate holds nothing back.",
                parameter,
            )
        )
    if component == "prepare.formula" and not parsed.names:
        issues.append(
            ValueIssue(
                "warning",
                "The formula reads no feature, so its value never changes.",
                parameter,
            )
        )
    return issues


VALUE_CHECKED = frozenset(
    {"prepare.math", "prepare.change", "prepare.formula", "prepare.gate"}
)

__all__ = [
    "VALUE_CHECKED",
    "Aggregate",
    "Formula",
    "Gate",
    "RowStep",
    "ValueIssue",
    "combined_columns",
    "combined_name",
    "expression",
    "row_step",
    "value_issues",
]
