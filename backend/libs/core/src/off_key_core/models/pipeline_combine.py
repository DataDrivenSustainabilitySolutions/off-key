"""Aggregate, Formula and Gate: Prepare steps over the whole row.

They keep no state and have output from the first observation. Aggregate and
Formula compute one feature, which follows the features they keep; Gate holds
back the observations its condition rejects. A Formula for each feature runs
its expression once per chosen feature, with x standing for that feature, and
adds or replaces one feature each. The compiler names and bounds their
features here, checks the values Prepare steps will skip, and RADAR runs the
steps built here.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..schemas.pipelines import FORMULA_SUFFIX, FORMULA_VARIABLE, FeatureDescription
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
from .pipeline_scope import MAX_FEATURE_NAME_LENGTH, ScopeError, adds, step_scope

Row = Mapping[str, float]
Columns = list[FeatureDescription]
_DEFAULT_NAMES = {
    "prepare.formula": "formula",
    "prepare.constant": "constant",
    "prepare.condition": "condition",
    "prepare.set": "feature",
}
_CONDITIONS = frozenset({"prepare.gate", "prepare.condition"})
NAMED_COMPONENTS = frozenset({"prepare.constant", "prepare.condition", "prepare.set"})


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
    """A numeric expression or condition; errors name their setting."""
    parameter = parsed_parameter(component)
    try:
        return parse(params[parameter], condition=component in _CONDITIONS)
    except FormulaError as error:
        error.parameter = parameter
        raise


def for_each(component: str, params: Mapping[str, Any]) -> bool:
    """Whether a Formula runs once for each of several features."""
    return component == "prepare.formula" and params.get("apply_to") is not None


@dataclass(frozen=True)
class EachScope:
    """The features a Formula for each feature uses, and the names it writes."""

    selected: tuple[str, ...]
    targets: tuple[str, ...]
    """Each selected feature's own name when it replaces, otherwise an added name."""
    add: bool


def each_scope(params: Mapping[str, Any], names: Sequence[str]) -> EachScope:
    """Resolve a Formula for each feature against the features that reach it."""
    available = set(names)
    if FORMULA_VARIABLE in available:
        raise ScopeError(
            f"A feature named {FORMULA_VARIABLE} arrives here, and in a formula for "
            f"each feature {FORMULA_VARIABLE} stands for that feature. Rename the "
            "feature first.",
            "apply_to",
        )
    selected = tuple(params["apply_to"])
    missing = next((name for name in selected if name not in available), None)
    if missing is not None:
        raise ScopeError(f"{missing} is not available at this step.", "apply_to")
    add = adds("prepare.formula", dict(params))
    if not add:
        return EachScope(selected, selected, add)
    suffix = params.get("suffix") or FORMULA_SUFFIX
    targets = tuple(f"{name}_{suffix}" for name in selected)
    taken = next((name for name in targets if name in available), None)
    if taken is not None:
        raise ScopeError(f"{taken} already exists. Choose another suffix.", "suffix")
    long = next((name for name in targets if len(name) > MAX_FEATURE_NAME_LENGTH), None)
    if long is not None:
        raise ScopeError(
            f"{long[:40]}… is longer than {MAX_FEATURE_NAME_LENGTH} characters. "
            "Choose a shorter suffix.",
            "suffix",
        )
    return EachScope(selected, targets, add)


def _readable(component: str, params: Mapping[str, Any], names: Sequence[str]):
    """The names an expression may read: x as well, in a formula for each feature."""
    if for_each(component, params):
        return [*names, FORMULA_VARIABLE]
    return list(names)


def _checked(component: str, params: Mapping[str, Any], names: Sequence[str]):
    parsed = expression(component, params)
    variable = parsed.references.get(FORMULA_VARIABLE)
    if (
        component == "prepare.formula"
        and variable is not None
        and not for_each(component, params)
        and FORMULA_VARIABLE not in names
    ):
        error = FormulaError(
            f"{FORMULA_VARIABLE} stands for each feature only in a formula for "
            "each feature. Choose the features under For each, or write a "
            "feature's name",
            variable.start,
        )
        error.parameter = parsed_parameter(component)
        raise error
    try:
        parsed.check_names(_readable(component, params, names))
    except FormulaError as error:
        error.parameter = parsed_parameter(component)
        raise
    return parsed


def parsed_parameter(component: str) -> str:
    return "condition" if component in _CONDITIONS else "expression"


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
class FormulaForEach:
    """An expression run once per chosen feature, with x standing for it."""

    expression: Expression
    evaluate: Callable[[Row], Any]
    scope: EachScope

    def apply(self, row: Row) -> dict[str, float]:
        # Every value is computed from the incoming row, so the order of the
        # chosen features never changes a result.
        values = [
            float(self.evaluate({**row, FORMULA_VARIABLE: row[name]}))
            for name in self.scope.selected
        ]
        return {**row, **dict(zip(self.scope.targets, values, strict=True))}


@dataclass(frozen=True)
class Gate:
    """Lets an observation on when its condition holds; features pass unchanged."""

    expression: Expression
    evaluate: Callable[[Row], Any]

    def opens(self, row: Row) -> bool:
        return bool(self.evaluate(row))


@dataclass(frozen=True)
class NamedValue:
    """Write one feature; dictionary assignment keeps an existing field's order."""

    name: str
    evaluate: Callable[[Row], Any]

    def apply(self, row: Row) -> dict[str, float]:
        return {**row, self.name: _finite(float(self.evaluate(row)))}


RowStep = Aggregate | Formula | FormulaForEach | Gate | NamedValue


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
    if component == "prepare.constant":
        value = _setting(component, params, "value")
        return NamedValue(combined_name(component, params), lambda _row: value)
    parsed = _checked(component, params, inputs)
    if component == "prepare.gate":
        return Gate(parsed, evaluator(parsed))
    if component in NAMED_COMPONENTS:
        return NamedValue(combined_name(component, params), evaluator(parsed))
    if for_each(component, params):
        return FormulaForEach(parsed, evaluator(parsed), each_scope(params, inputs))
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
    """The features after a stateless row operation."""
    names = [item.name for item in columns]
    if component in NAMED_COMPONENTS:
        return _named_columns(component, params, columns)
    if component == "prepare.gate":
        _checked(component, params, names)
        return columns
    if for_each(component, params):
        return _each_columns(params, columns)
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


def _named_columns(
    component: str, params: Mapping[str, Any], columns: Columns
) -> Columns:
    name = combined_name(component, params)
    names = [item.name for item in columns]
    if name in names and component != "prepare.set":
        raise ScopeError(f"{name} already exists. Choose another name.", "name")
    used = ()
    if component == "prepare.constant":
        low = high = _setting(component, params, "value")
    else:
        parsed = _checked(component, params, names)
        used = parsed.names
        analysis = analyze(parsed, _bounds(columns))
        if component == "prepare.condition":
            low, high = (
                (0.0, 1.0) if analysis.truth is None else (float(analysis.truth),) * 2
            )
        else:
            low, high = analysis.low, analysis.high
    result = FeatureDescription(
        name=name,
        raw=False,
        minimum=low,
        maximum=high,
        slots=sorted(
            {slot for item in columns if item.name in used for slot in item.slots}
        ),
    )
    if name in names:
        return [result if item.name == name else item for item in columns]
    return [*columns, result]


def _each_bounds(columns: Columns, name: str) -> dict[str, Bounds]:
    """The ranges a formula for each feature reads, with x as that feature."""
    bounds = _bounds(columns)
    bounds[FORMULA_VARIABLE] = bounds[name]
    return bounds


def _each_columns(params: Mapping[str, Any], columns: Columns) -> Columns:
    """The features after a Formula for each feature: each chosen feature is
    replaced in place, or followed at the end by the feature computed from it."""
    names = [item.name for item in columns]
    parsed = _checked("prepare.formula", params, names)
    scope = each_scope(params, names)
    position = {item.name: item for item in columns}
    # Every computed feature also depends on the other features the formula reads.
    shared = sorted(
        {
            slot
            for name in parsed.names
            if name != FORMULA_VARIABLE
            for slot in position[name].slots
        }
    )
    computed = []
    for name, target in zip(scope.selected, scope.targets, strict=True):
        analysis = analyze(parsed, _each_bounds(columns, name))
        source = position[name]
        item = source if not scope.add else source.model_copy(deep=True)
        item.name = target
        item.minimum, item.maximum = analysis.low, analysis.high
        item.slots = sorted({*source.slots, *shared})
        item.raw = False
        computed.append(item)
    return columns + computed if scope.add else columns


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
    if component in {
        "prepare.formula",
        "prepare.gate",
        "prepare.condition",
        "prepare.set",
    }:
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
    if for_each(component, params):
        return _each_issues(params, parsed, columns, labels)
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


def _each_issues(
    params: Mapping[str, Any],
    parsed: Expression,
    columns: Columns,
    labels: Mapping[str, str],
) -> list[ValueIssue]:
    """Values skipped for any of the features, with x named as that feature."""
    issues: list[ValueIssue] = []
    for name in params["apply_to"]:
        named = {**labels, FORMULA_VARIABLE: labels.get(name, name)}
        analysis = analyze(parsed, _each_bounds(columns, name), named)
        for severity, texts in (
            ("error", analysis.errors),
            ("warning", analysis.warnings),
        ):
            for text in texts:
                issue = ValueIssue(severity, text, "expression")
                if issue not in issues:
                    issues.append(issue)
    if FORMULA_VARIABLE not in parsed.names:
        issues.append(
            ValueIssue(
                "warning",
                f"The formula never reads {FORMULA_VARIABLE}, so every feature it "
                "applies to gets the same value.",
                "expression",
            )
        )
    return issues


VALUE_CHECKED = frozenset(
    {
        "prepare.math",
        "prepare.change",
        "prepare.formula",
        "prepare.gate",
        "prepare.condition",
        "prepare.set",
    }
)

__all__ = [
    "VALUE_CHECKED",
    "Aggregate",
    "EachScope",
    "Formula",
    "FormulaForEach",
    "Gate",
    "RowStep",
    "ValueIssue",
    "combined_columns",
    "combined_name",
    "each_scope",
    "expression",
    "for_each",
    "row_step",
    "value_issues",
]
