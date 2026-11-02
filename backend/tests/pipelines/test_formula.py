"""The formula language: parsing, evaluation and the ranges the compiler infers."""

import math
import random

import pytest
from off_key_core.models.pipeline_formula import (
    FormulaError,
    analyze,
    evaluator,
    parse,
)
from off_key_core.models.pipeline_prepare import PrepareFailure


def value(text, **row):
    return evaluator(parse(text))(row)


def holds(text, **row):
    return evaluator(parse(text, condition=True))(row)


def problem(text, *, condition=False):
    with pytest.raises(FormulaError) as raised:
        parse(text, condition=condition)
    return str(raised.value)


def skipped(text, **row):
    with pytest.raises(PrepareFailure) as raised:
        value(text, **row)
    return raised.value.reason, str(raised.value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 + 3 * 4 ^ 2", 50.0),
        ("(2 + 3) * 4", 20.0),
        ("10 - 4 - 3", 3.0),
        ("12 / 3 / 2", 2.0),
        # A sign binds less tightly than a power, which groups to the right.
        ("-2 ^ 2", -4.0),
        ("2 ^ 3 ^ 2", 512.0),
        ("2 ^ -1", 0.5),
        ("--3", 3.0),
        ("+3", 3.0),
        ("1.5e2 + .5", 150.5),
        ("abs(-3) + sqrt(16) + log(1) + log1p(0) + exp(0)", 8.0),
        ("min(3, 1, 2) + max(3, 1, 2)", 4.0),
        ("clip(5, 0, 1) + clip(-5, 0, 1) + clip(0.5, 0, 1)", 1.5),
    ],
)
def test_arithmetic_follows_the_usual_precedence(text, expected):
    assert value(text) == pytest.approx(expected)


def test_names_are_read_from_the_row_and_backticks_hold_other_characters():
    assert value("dc_voltage * dc_current", dc_voltage=400.0, dc_current=2.5) == 1000
    assert value("`dc-voltage` / 2", **{"dc-voltage": 9.0}) == 4.5
    expression = parse("a + b * a + `c d`")
    assert expression.names == ("a", "b", "c d")


@pytest.mark.parametrize(
    ("text", "row", "expected"),
    [
        ("a > 1", {"a": 2.0}, True),
        ("a >= 2 and a <= 2", {"a": 2.0}, True),
        ("a == 1 or a != 1", {"a": 5.0}, True),
        ("not a < 0", {"a": -1.0}, False),
        ("not (a > 0 and a < 1)", {"a": 0.5}, False),
        # and binds tighter than or.
        ("a > 0 or a > 1 and a < 0", {"a": 2.0}, True),
        # A guard keeps log from seeing a value outside its domain.
        ("a > 0 and log(a) > 1", {"a": -1.0}, False),
        ("a <= 0 or log(a) > 1", {"a": -1.0}, True),
    ],
)
def test_conditions_compare_and_join(text, row, expected):
    assert holds(text, **row) is expected


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a +", "The expression ends too early at character 4."),
        ("   ", "Write an expression."),
        ("(a + 1", "Close the parenthesis opened at character 1."),
        ("a b", "Unexpected b at character 3."),
        ("a $ b", "Unexpected character '$' at character 3."),
        ("a = 1", "Compare with == at character 3."),
        ("a ! 1", "Compare with !=, or negate with not at character 3."),
        ("lgo(a)", "Unknown function lgo at character 1. Did you mean log?"),
        ("min(a)", "min takes at least 2 values at character 1."),
        (
            "clip(a, 1)",
            "clip takes 3 values: the value, its low and its high end at character 1.",
        ),
        ("abs(a, b)", "abs takes 1 value at character 1."),
        ("max(a, b", "Close the parenthesis of max at character 1."),
        ("`log`(a)", "Functions are written without backticks at character 1."),
        ("`a", "Close the name that starts with ` at character 1."),
        ("`` + 1", "Write a feature name between the backticks at character 1."),
        ("1e999", "1e999 is too large at character 1."),
        ("-(a > 1)", "Use a number here, not a condition at character 2."),
        ("a * ", "The expression ends too early at character 5."),
        (
            "a > 1",
            "A formula computes a number; to hold observations back by a "
            "condition, use a Gate step.",
        ),
    ],
)
def test_a_formula_that_cannot_be_read_says_where_and_why(text, message):
    assert problem(text) == message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a", "Write a condition, such as dc_current > 1."),
        ("a < b < c", "Join two comparisons with and at character 7."),
        ("a > 1 and b", "Use a condition here, such as x > 0 at character 11."),
        ("not a", "Use a condition here, such as x > 0 at character 5."),
        ("(a > 1) + 1 > 0", "Use a number here, not a condition at character 1."),
    ],
)
def test_a_condition_must_compare(text, message):
    assert problem(text, condition=True) == message


def test_unknown_features_suggest_the_closest_one_that_arrives():
    expression = parse("dc_votlage * dc_current")
    with pytest.raises(FormulaError) as raised:
        expression.check_names(["dc_voltage", "dc_current"])
    assert str(raised.value) == (
        "Unknown feature dc_votlage at character 1. Did you mean dc_voltage?"
    )
    assert raised.value.position == 0
    with pytest.raises(FormulaError, match=r"^Unknown feature zzz at character 1\.$"):
        parse("zzz").check_names(["a"])


def test_length_nesting_and_chains_are_bounded():
    assert problem("a" * 513) == "Keep expressions to 512 characters."
    assert (
        problem("(" * 33 + "a" + ")" * 33) == "Nest at most 32 levels at character 33."
    )
    assert problem("-" * 40 + "a").startswith("Nest at most 32 levels")
    assert problem(" + ".join(["a"] * 120)) == (
        "Keep the expression to 100 nested operations; an Aggregate step sums or "
        "averages many features."
    )
    # A long sum that stays within both limits parses and evaluates.
    assert value(" + ".join(["a"] * 99), a=1.0) == 99


@pytest.mark.parametrize(
    ("text", "row", "reason", "message"),
    [
        ("a / b", {"a": 1.0, "b": 0.0}, "out_of_domain", "Division by 0"),
        ("log(a)", {"a": 0.0}, "out_of_domain", "log needs values above 0, not 0"),
        ("log1p(a)", {"a": -1.0}, "out_of_domain", "log1p needs values above -1"),
        ("sqrt(a)", {"a": -4.0}, "out_of_domain", "sqrt needs values of at least 0"),
        ("a ^ 0.5", {"a": -1.0}, "out_of_domain", "-1 ^ 0.5 is not a real number"),
        ("a ^ -1", {"a": 0.0}, "out_of_domain", "0 cannot be raised to a negative"),
        ("exp(a)", {"a": 1000.0}, "non_finite", "not a finite number"),
        ("a * a", {"a": 1e200}, "non_finite", "not a finite number"),
        ("a + a", {"a": 1.7e308}, "non_finite", "not a finite number"),
        ("a ^ 400", {"a": 10.0}, "non_finite", "not a finite number"),
    ],
)
def test_values_without_a_finite_result_skip_the_observation(
    text, row, reason, message
):
    found, text = skipped(text, **row)
    assert found == reason
    assert message in text


def test_ranges_follow_the_arithmetic():
    bounds = {"a": (0.0, 10.0), "b": (-1.0, 2.0), "c": (1.0, None)}

    def bounds_of(text):
        analysis = analyze(parse(text), bounds)
        assert analysis.warnings == analysis.errors == []
        return analysis.low, analysis.high

    assert bounds_of("a * b") == (-10.0, 20.0)
    assert bounds_of("a - b") == (-2.0, 11.0)
    assert bounds_of("b ^ 2") == (0.0, 4.0)
    assert bounds_of("b ^ 3") == (-1.0, 8.0)
    assert bounds_of("abs(b)") == (0.0, 2.0)
    assert bounds_of("clip(a, 2, 3)") == (2.0, 3.0)
    assert bounds_of("min(a, b)") == (-1.0, 2.0)
    assert bounds_of("max(a, b)") == (0.0, 10.0)
    assert bounds_of("a / c") == (0.0, 10.0)
    assert bounds_of("sqrt(a)") == (0.0, math.sqrt(10.0))
    # Unknown ends stay open.
    assert bounds_of("c + 1") == (2.0, None)
    assert bounds_of("exp(c)") == (math.e, None)
    assert bounds_of("1 / c") == (0.0, 1.0)


@pytest.mark.parametrize(
    ("text", "bounds", "warnings", "errors"),
    [
        (
            "a / b",
            {"b": (0.0, 5.0)},
            ["Division by Bee: observations where it is 0 are skipped."],
            [],
        ),
        (
            "a / (b - 1)",
            {"b": (1.0, 1.0)},
            [],
            [
                "Division by (b - 1): it is always 0, so every observation would "
                "be skipped."
            ],
        ),
        (
            "a / 0",
            {},
            [],
            ["Division by 0 is undefined, so every observation would be skipped."],
        ),
        (
            "log(b)",
            {"b": (-1.0, 5.0)},
            ["log of Bee: values at or below 0 are skipped."],
            [],
        ),
        (
            "log(b)",
            {"b": (-5.0, 0.0)},
            [],
            [
                "log of Bee: every value is at or below 0, so every observation "
                "would be skipped."
            ],
        ),
        ("sqrt(b)", {}, ["sqrt of Bee: values below 0 are skipped."], []),
        ("sqrt(b)", {"b": (0.0, None)}, [], []),
        (
            "b ^ 0.5",
            {"b": (-1.0, 4.0)},
            ["b ^ 0.5: observations where Bee is below 0 are skipped."],
            [],
        ),
        (
            "b ^ -0.5",
            {"b": (-4.0, 0.0)},
            [],
            ["b ^ -0.5: Bee is never above 0, so every observation would be skipped."],
        ),
        (
            "clip(a, 1, 0)",
            {},
            [],
            ["clip(a, 1, 0): the low end is above the high end."],
        ),
    ],
)
def test_values_a_formula_will_skip_are_named(text, bounds, warnings, errors):
    analysis = analyze(parse(text), bounds, {"b": "Bee"})
    assert (analysis.warnings, analysis.errors) == (warnings, errors)


@pytest.mark.parametrize(
    ("text", "truth"),
    [
        ("a > 20", False),
        ("a >= 0", True),
        ("a > 5", None),
        ("a < 0 or a > 10", False),
        ("a >= 0 and a <= 10", True),
        ("not a > 20", True),
        ("a == 11", False),
        ("a != 11", True),
        ("a > 5 and a > 20", False),
        ("a > 5 or a >= 0", True),
    ],
)
def test_a_condition_can_be_always_never_or_sometimes_true(text, truth):
    assert analyze(parse(text, condition=True), {"a": (0.0, 10.0)}).truth is truth


# A generator of formulas that are mostly well formed, so the fuzzing reaches
# evaluation and range analysis as well as the parser's errors.
_ATOMS = ["a", "b", "c", "0", "1", "2", "0.5", "-1", "1e3", "`b`"]
_UNARY = ["abs", "sqrt", "log", "log1p", "exp"]
_JOINS = [" + ", " - ", " * ", " / ", " ^ "]
_NOISE = ["(", ")", ",", " and ", " or ", " not ", " < ", " == ", "=", "$", "min("]


def _formula(rng, depth=0):
    roll = rng.random()
    if depth > 4 or roll < 0.3:
        return rng.choice(_ATOMS)
    if roll < 0.45:
        return f"{rng.choice(_UNARY)}({_formula(rng, depth + 1)})"
    if roll < 0.55:
        args = ", ".join(_formula(rng, depth + 1) for _ in range(rng.randint(2, 3)))
        return f"{rng.choice(['min', 'max'])}({args})"
    if roll < 0.6:
        parts = [_formula(rng, depth + 1) for _ in range(3)]
        return f"clip({', '.join(parts)})"
    if roll < 0.65:
        return f"-{_formula(rng, depth + 1)}"
    if roll < 0.75:
        return f"({_formula(rng, depth + 1)})"
    return f"{_formula(rng, depth + 1)}{rng.choice(_JOINS)}{_formula(rng, depth + 1)}"


def _garbled(rng, text):
    pieces = list(text)
    for _ in range(rng.randint(1, 3)):
        position = rng.randrange(len(pieces) + 1)
        pieces.insert(position, rng.choice(_NOISE))
    return "".join(pieces)


def _checked(expression, analysis, row, condition, text) -> bool:
    """Evaluate one row; False when the observation is skipped."""
    try:
        result = evaluator(expression)(row)
    except PrepareFailure as failure:
        assert failure.reason in {"out_of_domain", "non_finite"}
        return False
    if condition:
        assert isinstance(result, bool)
        assert analysis.truth is None or result is analysis.truth, text
        return True
    assert math.isfinite(result), text
    # The inferred range holds every value the formula produces.
    slack = 1e-9 * max(1.0, abs(result))
    assert analysis.low is None or result >= analysis.low - slack, text
    assert analysis.high is None or result <= analysis.high + slack, text
    return True


def test_any_text_parses_or_names_its_problem_and_evaluation_only_skips():
    rng = random.Random(20261101)
    bounds = {"a": (-2.0, 3.0), "b": (0.0, 1.0), "c": (None, None)}
    parsed = evaluated = skips = 0
    for index in range(3000):
        text = _formula(rng)
        if index % 3 == 0:
            text = _garbled(rng, text)
        condition = index % 5 == 0
        if condition:
            text = f"{text} {rng.choice(['<', '>=', '!='])} {_formula(rng)}"
        try:
            expression = parse(text, condition=condition)
            expression.check_names(["a", "b", "c"])
        except FormulaError as error:
            assert str(error).endswith((".", "?"))
            continue
        parsed += 1
        analysis = analyze(expression, bounds)
        for _ in range(4):
            row = {
                "a": rng.uniform(-2.0, 3.0),
                "b": rng.choice([0.0, 1.0, rng.random()]),
                "c": rng.choice([-1e6, -1.0, 0.0, 1.0, 1e6, rng.gauss(0, 10)]),
            }
            if _checked(expression, analysis, row, condition, text):
                evaluated += 1
            else:
                skips += 1
    assert parsed > 1000 and evaluated > 1000 and skips > 100
