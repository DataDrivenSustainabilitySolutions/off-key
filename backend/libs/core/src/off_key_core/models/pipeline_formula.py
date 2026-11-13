"""Formulas and gate conditions over features: a small parser, never eval.

A formula is arithmetic over the features that arrive at its step. A condition
compares formulas and joins the comparisons with and, or and not. Both parse
into one tree that three readers share: the compiler checks names and types
and infers the range of values, RADAR evaluates it once per observation, and
the composer lists the features it uses.
"""

from __future__ import annotations

import difflib
import math
import operator
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .pipeline_formula_guards import assume
from .pipeline_prepare import Bounds, PrepareFailure

MAX_EXPRESSION_LENGTH = 512
MAX_DEPTH = 32
"""Levels of parentheses, signs and calls the parser descends into."""
MAX_TREE_DEPTH = 100
"""Levels of the parsed tree, long chains of operators included, so checking
and evaluating it stay far from Python's recursion limit."""

FUNCTIONS: dict[str, tuple[int, int | None]] = {
    "abs": (1, 1),
    "sqrt": (1, 1),
    "log": (1, 1),
    "log1p": (1, 1),
    "exp": (1, 1),
    "sign": (1, 1),
    "floor": (1, 1),
    "ceil": (1, 1),
    "round": (1, 1),
    "sin": (1, 1),
    "cos": (1, 1),
    "mod": (2, 2),
    "atan2": (2, 2),
    "hypot": (2, None),
    "min": (2, None),
    "max": (2, None),
    "mean": (2, None),
    "sum": (2, None),
    "clip": (3, 3),
    "if": (3, 3),
    "pi": (0, 0),
}
COMPARISONS = ("<=", ">=", "==", "!=", "<", ">")
KEYWORDS = frozenset({"and", "or", "not"})
_NUMBER = re.compile(r"(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*", re.ASCII)
_ARITY = {
    "mod": "2 values: the value and what it is divided by",
    "atan2": "2 values: y and x",
    "clip": "3 values: the value, its low and its high end",
    "if": "3 arguments: a condition, its true value and its false value",
    "pi": "no value: write pi()",
}


def _arity(function: str) -> str:
    """How many values a function takes, in words."""
    if function in _ARITY:
        return _ARITY[function]
    return "1 value" if FUNCTIONS[function] == (1, 1) else "at least 2 values"


class FormulaError(ValueError):
    """An expression that cannot be used, named by its first problem."""

    def __init__(
        self,
        message: str,
        position: int | None = None,
        hint: str | None = None,
        *,
        fix: tuple[int, int, str] | None = None,
    ):
        self.message = message
        self.hint = hint
        self.position = position
        """Index of the first character concerned, from 0."""
        self.parameter: str | None = None
        """The setting that holds the expression, once a step names it."""
        self.fix = fix
        """Characters start to end that the hint replaces, and the text it writes."""
        text = message if position is None else f"{message} at character {position + 1}"
        super().__init__(f"{text}." + (f" Did you mean {hint}?" if hint else ""))


def written(name: str) -> str | None:
    """A feature name as a formula writes it: bare when it can be, otherwise
    between backticks. None for a name no formula can write."""
    if _NAME.fullmatch(name) and name not in KEYWORDS:
        return name
    return None if "`" in name else f"`{name}`"


def _suggested(
    message: str, term_start: int, term_end: int, hint: str | None, text: str | None
) -> FormulaError:
    """An unknown name, with the closest known one offered as its replacement."""
    fix = (term_start, term_end, text) if hint and text else None
    return FormulaError(message, term_start, hint, fix=fix)


@dataclass(frozen=True, slots=True)
class Term:
    """A node of a parsed expression and the characters it covers."""

    kind: str
    """number, name, negate, not, arithmetic, compare, logic or call."""
    start: int
    end: int
    value: Any = None
    """The number, feature name, operator or function."""
    args: tuple[Term, ...] = ()


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str
    start: int
    value: Any = None


def _tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        token = _token(text, index)
        tokens.append(token)
        index += len(token.text)
    tokens.append(_Token("end", "", len(text)))
    return tokens


def _token(text: str, index: int) -> _Token:
    if number := _NUMBER.match(text, index):
        value = float(number.group())
        if not math.isfinite(value):
            raise FormulaError(f"{number.group()} is too large", index)
        return _Token("number", number.group(), index, value)
    if name := _NAME.match(text, index):
        word = name.group()
        return _Token("keyword" if word in KEYWORDS else "name", word, index, word)
    if text[index] == "`":
        end = text.find("`", index + 1)
        if end < 0:
            raise FormulaError("Close the name that starts with `", index)
        if end == index + 1:
            raise FormulaError("Write a feature name between the backticks", index)
        return _Token("name", text[index : end + 1], index, text[index + 1 : end])
    return _operator(text, index)


def _operator(text: str, index: int) -> _Token:
    pair = text[index : index + 2]
    if pair in COMPARISONS:
        return _Token("op", pair, index)
    char = text[index]
    if char in "+-*/^(),<>":
        return _Token("op", char, index)
    if char == "=":
        raise FormulaError("Compare with ==", index)
    if char == "!":
        raise FormulaError("Compare with !=, or negate with not", index)
    raise FormulaError(f"Unexpected character {char!r}", index)


class _Parser:
    """Recursive descent, loosest binding first: or, and, not, comparison,
    sum, product, sign, power, value."""

    def __init__(self, text: str):
        self.tokens = _tokens(text)
        self.index = 0
        self.depth = 0

    @property
    def token(self) -> _Token:
        return self.tokens[self.index]

    def accept(self, *texts: str) -> _Token | None:
        token = self.token
        if token.kind in {"op", "keyword"} and token.text in texts:
            self.index += 1
            return token
        return None

    def nested(self, parse: Callable[[], Term], start: int) -> Term:
        """Parse one level deeper; start is where that level opens."""
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError(f"Nest at most {MAX_DEPTH} levels", start)
        try:
            return parse()
        finally:
            self.depth -= 1

    def parse(self) -> Term:
        if self.token.kind == "end":
            raise FormulaError("Write an expression")
        term = self.disjunction()
        if self.token.kind != "end":
            raise FormulaError(f"Unexpected {self.token.text}", self.token.start)
        return term

    def _joined(self, keyword: str, operand: Callable[[], Term]) -> Term:
        left = operand()
        while self.accept(keyword):
            right = operand()
            left = Term("logic", left.start, right.end, keyword, (left, right))
        return left

    def disjunction(self) -> Term:
        return self._joined("or", self.conjunction)

    def conjunction(self) -> Term:
        return self._joined("and", self.negation)

    def negation(self) -> Term:
        if token := self.accept("not"):
            operand = self.nested(self.negation, token.start)
            return Term("not", token.start, operand.end, "not", (operand,))
        return self.comparison()

    def comparison(self) -> Term:
        left = self.sum()
        token = self.accept(*COMPARISONS)
        if token is None:
            return left
        right = self.sum()
        if self.token.kind == "op" and self.token.text in COMPARISONS:
            raise FormulaError("Join two comparisons with and", self.token.start)
        return Term("compare", left.start, right.end, token.text, (left, right))

    def _chain(self, operators: tuple[str, ...], operand: Callable[[], Term]) -> Term:
        left = operand()
        while token := self.accept(*operators):
            right = operand()
            left = Term("arithmetic", left.start, right.end, token.text, (left, right))
        return left

    def sum(self) -> Term:
        return self._chain(("+", "-"), self.product)

    def product(self) -> Term:
        return self._chain(("*", "/"), self.sign)

    def sign(self) -> Term:
        if token := self.accept("-", "+"):
            operand = self.nested(self.sign, token.start)
            if token.text == "+":
                return operand
            return Term("negate", token.start, operand.end, "-", (operand,))
        return self.power()

    def power(self) -> Term:
        base = self.value()
        if caret := self.accept("^"):
            # Right-associative, and the exponent may carry a sign: 2 ^ -1.
            exponent = self.nested(self.sign, caret.start)
            return Term("arithmetic", base.start, exponent.end, "^", (base, exponent))
        return base

    def value(self) -> Term:
        token = self.token
        if token.kind == "number":
            self.index += 1
            return Term(
                "number", token.start, token.start + len(token.text), token.value
            )
        if token.kind == "name":
            self.index += 1
            following = self.token
            if following.kind == "op" and following.text == "(":
                if token.text.startswith("`"):
                    raise FormulaError(
                        "Functions are written without backticks", token.start
                    )
                return self.call(token)
            return Term("name", token.start, token.start + len(token.text), token.value)
        if self.accept("("):
            inner = self.nested(self.disjunction, token.start)
            close = self.accept(")")
            if close is None:
                raise FormulaError("Close the parenthesis opened", token.start)
            return Term(
                inner.kind, token.start, close.start + 1, inner.value, inner.args
            )
        if token.kind == "end":
            raise FormulaError("The expression ends too early", token.start)
        raise FormulaError(f"Expected a value, not {token.text}", token.start)

    def call(self, name: _Token) -> Term:
        function = name.value
        if function not in FUNCTIONS:
            hint = next(iter(difflib.get_close_matches(function, FUNCTIONS, n=1)), None)
            raise _suggested(
                f"Unknown function {function}",
                name.start,
                name.start + len(name.text),
                hint,
                hint,
            )
        self.accept("(")
        args: list[Term] = []
        if not self.accept(")"):
            args.append(self.nested(self.disjunction, name.start))
            while self.accept(","):
                args.append(self.nested(self.disjunction, name.start))
            if not self.accept(")"):
                raise FormulaError(f"Close the parenthesis of {function}", name.start)
        low, high = FUNCTIONS[function]
        if len(args) < low or (high is not None and len(args) > high):
            raise FormulaError(f"{function} takes {_arity(function)}", name.start)
        end = self.tokens[self.index - 1].start + 1
        return Term("call", name.start, end, function, tuple(args))


def _check_kind(term: Term) -> str:
    """number or condition; operands of the wrong kind are errors."""
    if term.kind == "call" and term.value == "if":
        _expect(term.args[0], "condition")
        for operand in term.args[1:]:
            _expect(operand, "number")
        return "number"
    match term.kind:
        case "compare":
            for operand in term.args:
                _expect(operand, "number")
            return "condition"
        case "logic" | "not":
            for operand in term.args:
                _expect(operand, "condition")
            return "condition"
        case _:
            for operand in term.args:
                _expect(operand, "number")
            return "number"


def _expect(term: Term, kind: str) -> None:
    if _check_kind(term) == kind:
        return
    if kind == "number":
        raise FormulaError("Use a number here, not a condition", term.start)
    raise FormulaError("Use a condition here, such as x > 0", term.start)


def _names(term: Term, found: dict[str, Term]) -> None:
    if term.kind == "name":
        found.setdefault(term.value, term)
    for operand in term.args:
        _names(operand, found)


@dataclass(frozen=True)
class Expression:
    """A parsed formula or condition and the features it reads."""

    text: str
    root: Term
    condition: bool
    references: dict[str, Term] = field(repr=False)
    """Each feature the expression reads, at its first mention."""

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.references)

    def check_names(self, available: Sequence[str]) -> None:
        """Refuse a name that does not arrive at the step, with a suggestion."""
        known = set(available)
        for name, term in self.references.items():
            if name not in known and FUNCTIONS.get(name) == (0, 0):
                # A constant is a function without values: pi().
                raise _suggested(
                    f"Unknown feature {name}",
                    term.start,
                    term.end,
                    f"{name}()",
                    f"{name}()",
                )
            if name not in known:
                hint = next(iter(difflib.get_close_matches(name, available, n=1)), None)
                raise _suggested(
                    f"Unknown feature {name}",
                    term.start,
                    term.end,
                    hint,
                    written(hint) if hint else None,
                )

    def describe(self, term: Term, labels: Mapping[str, str]) -> str:
        """A feature by its label, anything else as written."""
        if term.kind == "name" and self.text[term.start] != "(":
            return labels.get(term.value, term.value)
        return self.text[term.start : term.end]


def _tree_depth(root: Term) -> int:
    deepest = 0
    pending = [(root, 1)]
    while pending:
        term, level = pending.pop()
        deepest = max(deepest, level)
        pending.extend((operand, level + 1) for operand in term.args)
    return deepest


def parse(text: str, *, condition: bool = False) -> Expression:
    """Read a formula, or with condition=True a gate condition."""
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise FormulaError(f"Keep expressions to {MAX_EXPRESSION_LENGTH} characters")
    root = _Parser(text).parse()
    if _tree_depth(root) > MAX_TREE_DEPTH:
        raise FormulaError(
            f"Keep the expression to {MAX_TREE_DEPTH} nested operations; "
            "an Aggregate step sums or averages many features"
        )
    kind = _check_kind(root)
    if kind == "condition" and not condition:
        raise FormulaError(
            "A formula computes a number. For 1 or 0, write if(condition, 1, 0); "
            "to hold observations back by a condition, use a Gate step"
        )
    if kind == "number" and condition:
        raise FormulaError("Write a condition, such as dc_current > 1")
    references: dict[str, Term] = {}
    _names(root, references)
    return Expression(text, root, condition, references)


# Evaluation ---------------------------------------------------------------


Row = Mapping[str, float]
Evaluate = Callable[[Row], Any]


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise PrepareFailure("non_finite", "The result is not a finite number")
    return value


def _divide(dividend: float, divisor: float) -> float:
    if divisor == 0:
        raise PrepareFailure("out_of_domain", "Division by 0")
    return _finite(dividend / divisor)


def _power(base: float, exponent: float) -> float:
    try:
        return _finite(math.pow(base, exponent))
    except OverflowError:
        raise PrepareFailure(
            "non_finite", "The result is not a finite number"
        ) from None
    except ValueError:
        message = (
            "0 cannot be raised to a negative power"
            if base == 0
            else f"{base:g} ^ {exponent:g} is not a real number"
        )
        raise PrepareFailure("out_of_domain", message) from None


def _log(value: float) -> float:
    if value <= 0:
        raise PrepareFailure(
            "out_of_domain", f"log needs values above 0, not {value:g}"
        )
    return math.log(value)


def _log1p(value: float) -> float:
    if value <= -1:
        raise PrepareFailure(
            "out_of_domain", f"log1p needs values above -1, not {value:g}"
        )
    return math.log1p(value)


def _sqrt(value: float) -> float:
    if value < 0:
        raise PrepareFailure(
            "out_of_domain", f"sqrt needs values of at least 0, not {value:g}"
        )
    return math.sqrt(value)


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        raise PrepareFailure(
            "non_finite", "The result is not a finite number"
        ) from None


def _sign(value: float) -> float:
    return float((value > 0) - (value < 0))


def _round(value: float) -> float:
    """The nearest whole number; a half rounds away from 0, so 2.5 gives 3."""
    whole = math.floor(abs(value))
    if abs(value) - whole >= 0.5:
        whole += 1
    return math.copysign(whole, value)


def _mod(value: float, divisor: float) -> float:
    """The remainder with the divisor's sign, so mod(-1, 24) is 23."""
    if divisor == 0:
        raise PrepareFailure("out_of_domain", "mod by 0")
    return value % divisor


def _sum(values: list[float]) -> float:
    try:
        return _finite(math.fsum(values))
    except OverflowError:
        raise PrepareFailure(
            "non_finite", "The result is not a finite number"
        ) from None


def _mean(values: list[float]) -> float:
    return _sum(values) / len(values)


def _hypot(values: list[float]) -> float:
    return _finite(math.hypot(*values))


_ARITHMETIC: dict[str, Callable[[float, float], float]] = {
    "+": lambda left, right: _finite(left + right),
    "-": lambda left, right: _finite(left - right),
    "*": lambda left, right: _finite(left * right),
    "/": _divide,
    "^": _power,
}
_COMPARE: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}
_UNARY: dict[str, Callable[[float], float]] = {
    "abs": abs,
    "sqrt": _sqrt,
    "log": _log,
    "log1p": _log1p,
    "exp": _exp,
    "sign": _sign,
    "floor": lambda value: float(math.floor(value)),
    "ceil": lambda value: float(math.ceil(value)),
    "round": _round,
    "sin": math.sin,
    "cos": math.cos,
}
_BINARY: dict[str, Callable[[float, float], float]] = {
    "mod": _mod,
    "atan2": math.atan2,
}
# Functions of all their values at once.
_OVER: dict[str, Callable[[list[float]], float]] = {
    "min": min,
    "max": max,
    "mean": _mean,
    "sum": _sum,
    "hypot": _hypot,
}


def _compile(term: Term) -> Evaluate:
    args = [_compile(operand) for operand in term.args]
    match term.kind:
        case "number":
            constant = term.value
            return lambda _row: constant
        case "name":
            name = term.value
            return lambda row: row[name]
        case "negate":
            (inner,) = args
            return lambda row: -inner(row)
        case "not":
            (inner,) = args
            return lambda row: not inner(row)
        case "logic":
            left, right = args
            # Short-circuit, so a guard such as x > 0 and log(x) > 1 holds.
            if term.value == "and":
                return lambda row: left(row) and right(row)
            return lambda row: left(row) or right(row)
        case "compare" | "arithmetic":
            left, right = args
            apply = (_COMPARE if term.kind == "compare" else _ARITHMETIC)[term.value]
            return lambda row: apply(left(row), right(row))
    return _compile_call(term, args)


def _compile_call(term: Term, args: list[Evaluate]) -> Evaluate:
    function = term.value
    if function == "if":
        condition, when_true, when_false = args
        return lambda row: when_true(row) if condition(row) else when_false(row)
    if function in _UNARY:
        (inner,) = args
        unary = _UNARY[function]
        return lambda row: unary(inner(row))
    if function in _BINARY:
        left, right = args
        binary = _BINARY[function]
        return lambda row: binary(left(row), right(row))
    if function == "clip":
        value, low, high = args
        return lambda row: min(max(value(row), low(row)), high(row))
    if function == "pi":
        return lambda _row: math.pi
    over = _OVER[function]
    return lambda row: over([arg(row) for arg in args])


def evaluator(expression: Expression) -> Callable[[Row], Any]:
    """Evaluate on one row: a finite number, or a truth value for a condition.

    A value outside a function's domain, a division by 0 or a result that is
    not finite raises PrepareFailure, so its observation is skipped.
    """
    return _compile(expression.root)


# Ranges -------------------------------------------------------------------

INF = math.inf
Interval = tuple[float, float]


@dataclass
class Analysis:
    """What a parsed expression does over the ranges of its features."""

    low: float | None = None
    high: float | None = None
    truth: bool | None = None
    """For a condition: always true, never true, or None when it depends."""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def fail(self, message: str) -> None:
        if message not in self.errors:
            self.errors.append(message)


def interval(bounds: Bounds) -> Interval:
    low, high = bounds
    return (-INF if low is None else low, INF if high is None else high)


def known(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _product(left: float, right: float) -> float:
    # The bound of 0 times anything is 0, also against an open end.
    return 0.0 if left == 0 or right == 0 else left * right


def _multiply(left: Interval, right: Interval) -> Interval:
    products = [_product(a, b) for a in left for b in right]
    return min(products), max(products)


def _reciprocal(value: Interval) -> Interval:
    low, high = value
    if low > 0 or high < 0:
        return 1 / high, 1 / low
    if low == 0 and high > 0:
        return 1 / high, INF
    if high == 0 and low < 0:
        return -INF, 1 / low
    return -INF, INF


def _magnitude(value: Interval) -> Interval:
    low, high = value
    if low >= 0:
        return value
    if high <= 0:
        return -high, -low
    return 0.0, max(-low, high)


def _raised(value: float, exponent: float) -> float:
    try:
        return math.pow(value, exponent)
    except OverflowError:
        return INF if value > 0 or exponent % 2 == 0 else -INF
    except ValueError:
        return math.nan


def _constant(term: Term) -> float | None:
    if term.kind == "number":
        return term.value
    if term.kind == "negate":
        inner = _constant(term.args[0])
        return None if inner is None else -inner
    return None


def domain_issue(
    function: str, value: Interval, description: str
) -> tuple[str | None, str | None]:
    """A warning when some values lie outside log, log1p or sqrt's domain,
    an error when all of them do."""
    floor, strict = {"log": (0.0, True), "log1p": (-1.0, True), "sqrt": (0.0, False)}[
        function
    ]
    low, high = value
    outside = "at or below" if strict else "below"
    every = high <= floor if strict else high < floor
    some = low <= floor if strict else low < floor
    if every:
        return None, (
            f"{function} of {description}: every value is {outside} {floor:g}, "
            "so every observation would be skipped."
        )
    if some:
        return (
            f"{function} of {description}: values {outside} {floor:g} are skipped.",
            None,
        )
    return None, None


class _Ranges:
    def __init__(
        self,
        expression: Expression,
        bounds: Mapping[str, Bounds],
        labels: Mapping[str, str],
        analysis: Analysis,
        nonzero: frozenset[str] = frozenset(),
    ):
        self.expression = expression
        self.bounds = bounds
        self.labels = labels
        self.analysis = analysis
        self.nonzero_names = nonzero

    def describe(self, term: Term) -> str:
        return self.expression.describe(term, self.labels)

    def number(self, term: Term) -> Interval:
        args = term.args
        match term.kind:
            case "number":
                return term.value, term.value
            case "name":
                return interval(self.bounds.get(term.value, (None, None)))
            case "negate":
                low, high = self.number(args[0])
                return -high, -low
            case "arithmetic":
                return self.arithmetic(term)
        return self.call(term)

    def arithmetic(self, term: Term) -> Interval:
        left_term, right_term = term.args
        left, right = self.number(left_term), self.number(right_term)
        match term.value:
            case "+":
                return left[0] + right[0], left[1] + right[1]
            case "-":
                return left[0] - right[1], left[1] - right[0]
            case "*":
                return _multiply(left, right)
            case "/":
                self.nonzero(
                    right_term, right, f"Division by {self.describe(right_term)}"
                )
                return _multiply(left, _reciprocal(right))
        return self.power(term, left_term, left, right_term)

    def nonzero(self, term: Term, value: Interval, subject: str) -> None:
        """Dividing by a value that can be 0 skips those observations."""
        if term.kind == "name" and term.value in self.nonzero_names:
            return
        name = self.describe(term)
        itself = subject.endswith(name)
        if value == (0.0, 0.0) and _constant(term) is not None:
            self.analysis.fail(
                f"{subject} is undefined, so every observation would be skipped."
            )
        elif value == (0.0, 0.0):
            self.analysis.fail(
                f"{subject}: {'it' if itself else name} is always 0, "
                "so every observation would be skipped."
            )
        elif value[0] <= 0 <= value[1]:
            self.analysis.warn(
                f"{subject}: observations where {'it' if itself else name} "
                "is 0 are skipped."
            )

    def power(
        self, term: Term, base_term: Term, base: Interval, exponent_term: Term
    ) -> Interval:
        constant = _constant(exponent_term)
        written = self.describe(term)
        if constant is not None and constant == int(constant):
            whole = int(constant)
            if whole == 0:
                return 1.0, 1.0
            if whole < 0:
                self.nonzero(base_term, base, written)
                base, whole = _reciprocal(base), -whole
            if whole % 2 == 0:
                low, high = _magnitude(base)
                return _raised(low, whole), _raised(high, whole)
            return _raised(base[0], whole), _raised(base[1], whole)
        name = self.describe(base_term)
        if constant is None:
            # The exponent varies: a negative base works only for whole powers.
            if base[0] <= 0:
                self.analysis.warn(
                    f"{written}: observations where {name} is negative, or 0 "
                    "with a negative power, are skipped unless the power is whole."
                )
            return (0.0, INF) if base[0] > 0 else (-INF, INF)
        negative = constant < 0
        if base[1] < 0 or (negative and base[1] <= 0):
            self.analysis.fail(
                f"{written}: {name} is never "
                f"{'above' if negative else 'at least'} 0, "
                "so every observation would be skipped."
            )
            return -INF, INF
        if base[0] < 0 or (negative and base[0] <= 0):
            self.analysis.warn(
                f"{written}: observations where {name} is "
                f"{'at or below' if negative else 'below'} 0 are skipped."
            )
        low, high = max(base[0], 0.0), base[1]
        if negative:
            return _raised(high, constant), (
                INF if low == 0 else _raised(low, constant)
            )
        return _raised(low, constant), _raised(high, constant)

    def call(self, term: Term) -> Interval:
        function = term.value
        if function == "if":
            return self.choose(term)
        values = [self.number(operand) for operand in term.args]
        if function in {"log", "log1p", "sqrt"}:
            (value,) = values
            warning, error = domain_issue(function, value, self.describe(term.args[0]))
            if warning:
                self.analysis.warn(warning)
            if error:
                self.analysis.fail(error)
                return -INF, INF
            return _function_range(function, value)
        if function == "abs":
            return _magnitude(values[0])
        if function == "exp":
            low, high = values[0]
            return _exp_bound(low), _exp_bound(high)
        if function == "clip":
            value, low, high = values
            lower, upper = _constant(term.args[1]), _constant(term.args[2])
            if lower is not None and upper is not None and lower > upper:
                self.analysis.fail(
                    f"{self.describe(term)}: the low end is above the high end."
                )
            floor = max(value[0], low[0]), max(value[1], low[1])
            return min(floor[0], high[0]), min(floor[1], high[1])
        if function == "mod":
            divisor = term.args[1]
            self.nonzero(divisor, values[1], f"mod by {self.describe(divisor)}")
        return _call_range(function, values)

    def branch(self, condition: Term, truth: bool) -> _Ranges | None:
        refined = assume(condition, truth, self.bounds, self.nonzero_names)
        if refined is None:
            return None
        bounds, nonzero = refined
        return _Ranges(self.expression, bounds, self.labels, Analysis(), nonzero)

    def include(self, other: _Ranges, *, conditional: bool) -> None:
        for warning in other.analysis.warnings:
            self.analysis.warn(warning)
        for error in other.analysis.errors:
            if conditional:
                self.analysis.warn(
                    "For observations selecting this branch: "
                    + error.replace("every observation", "the observation")
                )
            else:
                self.analysis.fail(error)

    def choose(self, term: Term) -> Interval:
        condition, yes, no = term.args
        truth = self.condition(condition)
        outcomes = []
        for selected, value in ((True, yes), (False, no)):
            if truth is not None and truth != selected:
                continue
            branch = self.branch(condition, selected)
            if branch is not None:
                outcomes.append((branch.number(value), branch))
        for _, branch in outcomes:
            self.include(branch, conditional=len(outcomes) > 1)
        if outcomes and all(branch.analysis.errors for _, branch in outcomes):
            self.analysis.fail(
                "Every selected branch of if would skip the observation."
            )
        if not outcomes:
            return -INF, INF
        return min(value[0] for value, _ in outcomes), max(
            value[1] for value, _ in outcomes
        )

    def condition(self, term: Term) -> bool | None:
        match term.kind:
            case "not":
                inner = self.condition(term.args[0])
                return None if inner is None else not inner
            case "logic":
                left = self.condition(term.args[0])
                required = term.value == "and"
                if left is not None and left != required:
                    return left
                branch = self.branch(term.args[0], required)
                if branch is None:
                    return not required
                right = branch.condition(term.args[1])
                self.include(branch, conditional=left is None)
                if term.value == "and":
                    if left is False or right is False:
                        return False
                    return True if left and right else None
                if left or right:
                    return True
                return False if left is False and right is False else None
        left, right = (self.number(operand) for operand in term.args)
        return _compare(term.value, left, right)


def _function_range(function: str, value: Interval) -> Interval:
    """log, log1p or sqrt of the values in their domain; all are increasing."""
    low, high = value
    if function == "sqrt":
        return math.sqrt(max(low, 0.0)), math.sqrt(high)
    floor, apply = (0.0, math.log) if function == "log" else (-1.0, math.log1p)
    return (apply(low) if low > floor else -INF), apply(high)


def _whole(value: float, apply: Callable[[float], float]) -> float:
    """floor, ceil or round of an end of a range; an open end stays open."""
    return value if math.isinf(value) else float(apply(value))


def _mod_range(divisor: Interval) -> Interval:
    """A remainder lies between 0 and its divisor, on the divisor's side."""
    low, high = divisor
    return min(low, 0.0), max(high, 0.0)


def _angle_range(y: Interval, x: Interval) -> Interval:
    """atan2 by the half-planes its point can lie in.

    Left of the origin a y of 0 gives pi or -pi by its sign, and -0.0 counts
    as 0 in a range, so only a y that stays off 0 picks a side there.
    """
    if x[0] > 0:
        return (
            0.0 if y[0] >= 0 else -math.pi / 2,
            0.0 if y[1] <= 0 else math.pi / 2,
        )
    if y[0] > 0:
        return 0.0, math.pi
    if y[1] < 0:
        return -math.pi, 0.0
    return -math.pi, math.pi


def _wave_range(function: str, value: Interval) -> Interval:
    """sin or cos: exact for one value, otherwise the whole wave."""
    if value[0] == value[1] and math.isfinite(value[0]):
        result = (math.sin if function == "sin" else math.cos)(value[0])
        return result, result
    return -1.0, 1.0


def _sign_range(value: Interval) -> Interval:
    low, high = value
    return _sign(low), _sign(high)


def _total(ends: Sequence[float], open_end: float) -> float:
    """A sum of the low or the high ends of ranges; open_end is the end that
    stays open, which an open range or an overflow gives."""
    if any(math.isinf(end) for end in ends):
        return open_end
    try:
        return math.fsum(ends)
    except OverflowError:
        return open_end


def _call_range(function: str, values: list[Interval]) -> Interval:
    """The range of a function without a domain of its own to check."""
    # A power that is not a real number leaves an end unknown; read it as open.
    values = [
        (-INF, INF) if math.isnan(low) or math.isnan(high) else (low, high)
        for low, high in values
    ]
    lows = [low for low, _ in values]
    highs = [high for _, high in values]
    match function:
        case "sign":
            return _sign_range(values[0])
        case "floor" | "ceil" | "round":
            apply = {"floor": math.floor, "ceil": math.ceil, "round": _round}[function]
            return _whole(lows[0], apply), _whole(highs[0], apply)
        case "sin" | "cos":
            return _wave_range(function, values[0])
        case "mod":
            return _mod_range(values[1])
        case "atan2":
            return _angle_range(*values)
        case "pi":
            return math.pi, math.pi
        case "sum":
            return _total(lows, -INF), _total(highs, INF)
        case "mean":
            return (
                _total(lows, -INF) / len(values),
                _total(highs, INF) / len(values),
            )
        case "hypot":
            sizes = [_magnitude(value) for value in values]
            return (
                math.hypot(*(low for low, _ in sizes)),
                math.hypot(*(high for _, high in sizes)),
            )
    pick = min if function == "min" else max
    return pick(lows), pick(highs)


def _exp_bound(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return INF


def _compare(op: str, left: Interval, right: Interval) -> bool | None:
    if op in {">", ">="}:
        op, left, right = {">": "<", ">=": "<="}[op], right, left
    match op:
        case "<":
            if left[1] < right[0]:
                return True
            return False if left[0] >= right[1] else None
        case "<=":
            if left[1] <= right[0]:
                return True
            return False if left[0] > right[1] else None
    equal = None
    if left[0] == left[1] == right[0] == right[1]:
        equal = True
    elif left[1] < right[0] or right[1] < left[0]:
        equal = False
    if op == "==" or equal is None:
        return equal
    return not equal


def analyze(
    expression: Expression,
    bounds: Mapping[str, Bounds],
    labels: Mapping[str, str] | None = None,
) -> Analysis:
    """The range of a formula, or whether a condition can hold, from the
    ranges of the features it reads; warnings name what will be skipped."""
    analysis = Analysis()
    ranges = _Ranges(expression, bounds, labels or {}, analysis)
    if expression.condition:
        analysis.truth = ranges.condition(expression.root)
        return analysis
    low, high = ranges.number(expression.root)
    analysis.low = None if math.isnan(low) else known(low)
    analysis.high = None if math.isnan(high) else known(high)
    return analysis


__all__ = [
    "FUNCTIONS",
    "MAX_EXPRESSION_LENGTH",
    "Analysis",
    "Expression",
    "FormulaError",
    "Term",
    "analyze",
    "domain_issue",
    "evaluator",
    "parse",
    "written",
]
