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


@pytest.mark.parametrize("x", [-2.0, 0.0, 2.0])
def test_conditional_formulas_evaluate_only_the_selected_branch(x):
    assert value("if(x != 0, 1 / x, 0)", x=x) == (1 / x if x else 0)
    assert value("if(x > 0, log(x), if(x < 0, -x, 0))", x=x) == (
        math.log(x) if x > 0 else abs(x)
    )
    assert value("if(1 == 1, 7, sqrt(-1))") == 7
    assert holds("if(x > 0, x, 0) >= 0", x=x)


@pytest.mark.parametrize("text", ["if(a, 1, 0)", "if(a > 0, a > 1, 0)", "if(a > 0, 1)"])
def test_conditional_arguments_have_explicit_kinds(text):
    assert problem(text)


@pytest.mark.parametrize(
    "text",
    [
        "if(x != 0, 1 / x, 0)",
        "if(x > 0, log(x), 0)",
        "if(x >= 0, sqrt(x), sqrt(-x))",
        "if(not (x <= 0), log(x), 0)",
        "if(0 < x and x < 2, log(x), 0)",
        "if(x <= 0 or x >= 2, 0, log(x))",
        "if(1 > 0, 1, 1 / 0)",
    ],
)
def test_conditional_range_analysis_respects_guards(text):
    analysis = analyze(parse(text), {"x": (-2.0, 2.0)})
    assert analysis.errors == analysis.warnings == []


def test_conditionally_invalid_values_warn_without_blocking_the_valid_branch():
    analysis = analyze(parse("if(x > 0, sqrt(-1), 0)"), {"x": (-1.0, 1.0)})
    assert analysis.errors == [] and len(analysis.warnings) == 1
    assert analyze(parse("if(x > 0, sqrt(-1), 1 / 0)"), {}).errors
    bounded = analyze(parse("if(x > 0, 2, -3)"), {})
    assert (bounded.low, bounded.high) == (-3, 2)


@pytest.mark.parametrize(
    ("text", "row", "expected"),
    [
        ("sign(x)", {"x": -3.0}, -1),
        ("sign(x)", {"x": 0.0}, 0),
        ("sign(x)", {"x": 0.2}, 1),
        ("floor(x)", {"x": -1.5}, -2),
        ("ceil(x)", {"x": -1.5}, -1),
        # A half rounds away from 0, and the largest value below a half down.
        ("round(x)", {"x": 2.5}, 3),
        ("round(x)", {"x": -2.5}, -3),
        ("round(x)", {"x": 0.49999999999999994}, 0),
        ("round(x * 100) / 100", {"x": 3.14159}, 3.14),
        # The remainder takes the divisor's sign: an hour before midnight is 23.
        ("mod(x, 24)", {"x": -1.0}, 23),
        ("mod(x, 24)", {"x": 49.5}, 1.5),
        ("mod(x, -24)", {"x": 1.0}, -23),
        ("hypot(3, 4)", {}, 5),
        ("hypot(1, 2, 2)", {}, 3),
        ("mean(a, b, 6)", {"a": 1.0, "b": 2.0}, 3),
        ("sum(a, b, 6)", {"a": 1.0, "b": 2.0}, 9),
        ("2 * pi()", {}, 2 * math.pi),
        ("sin(pi() / 2)", {}, 1),
        ("cos(pi())", {}, -1),
        ("atan2(y, x)", {"y": 1.0, "x": -1.0}, 3 * math.pi / 4),
        ("atan2(0, 0)", {}, 0),
    ],
)
def test_more_functions_round_wrap_and_combine(text, row, expected):
    assert value(text, **row) == pytest.approx(expected)


def test_a_remainder_by_zero_skips_and_a_guard_prevents_it():
    with pytest.raises(PrepareFailure, match="mod by 0") as failure:
        value("mod(a, b)", a=1.0, b=0.0)
    assert failure.value.reason == "out_of_domain"
    bounds = {"a": (-5.0, 5.0), "b": (0.0, 24.0)}
    assert analyze(parse("mod(a, b)"), bounds, {"b": "Period"}).warnings == [
        "mod by Period: observations where it is 0 are skipped."
    ]
    assert analyze(parse("if(b != 0, mod(a, b), 0)"), bounds).warnings == []
    assert analyze(parse("mod(a, 0)"), bounds).errors == [
        "mod by 0 is undefined, so every observation would be skipped."
    ]
    with pytest.raises(PrepareFailure, match="finite"):
        value("sum(a, a)", a=1e308)


@pytest.mark.parametrize(
    ("text", "low", "high"),
    [
        ("sign(a)", -1, 1),
        ("sign(b)", 0, 1),
        ("floor(a)", -3, 3),
        ("ceil(a)", -2, 4),
        ("round(a)", -3, 4),
        ("mod(a, 24)", 0, 24),
        ("mod(a, -24)", -24, 0),
        ("mod(a, b)", 0, 1),
        ("mod(a, a)", -2.5, 3.5),
        ("hypot(a, b)", 0, math.hypot(3.5, 1)),
        ("mean(a, b)", -1.25, 2.25),
        ("sum(a, b, 1)", -1.5, 5.5),
        ("sin(a)", -1, 1),
        ("cos(0)", 1, 1),
        ("pi()", math.pi, math.pi),
        # Right of the origin an angle is at most a quarter turn either way.
        ("atan2(a, 1 + b)", -math.pi / 2, math.pi / 2),
        ("atan2(b, 1 + b)", 0, math.pi / 2),
        ("atan2(1 + b, a)", 0, math.pi),
        # Left of the origin a y of 0 gives pi or -pi, so nothing narrows.
        ("atan2(b, a)", -math.pi, math.pi),
        ("sum(a, c)", None, None),
        ("round(c)", None, None),
    ],
)
def test_more_functions_have_ranges(text, low, high):
    bounds = {"a": (-2.5, 3.5), "b": (0.0, 1.0), "c": (None, None)}
    analysis = analyze(parse(text), bounds)
    assert (analysis.low, analysis.high) == (low, high)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("2 * pi", "Unknown feature pi at character 5. Did you mean pi()?"),
        ("pi(1)", "pi takes no value: write pi() at character 1."),
        ("mod(1)", "mod takes 2 values: the value and what it is divided by"),
        ("atan2(1)", "atan2 takes 2 values: y and x"),
        ("hypot(1)", "hypot takes at least 2 values"),
        ("sign()", "sign takes 1 value"),
        ("mean(a > 1, 2)", "Use a number here, not a condition"),
    ],
)
def test_more_functions_name_their_problems(text, message):
    with pytest.raises(FormulaError) as error:
        parse(text).check_names(["a"])
    assert message in str(error.value)
    if text == "2 * pi":
        # One click writes the constant.
        assert error.value.fix == (4, 6, "pi()")


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
            "A formula computes a number. For 1 or 0, write if(condition, 1, 0); "
            "to hold observations back by a condition, use a Gate step.",
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
_ATOMS = ["a", "b", "c", "0", "1", "2", "0.5", "-1", "1e3", "`b`", "pi()"]
_UNARY = [
    *("abs", "sqrt", "log", "log1p", "exp"),
    *("sign", "floor", "ceil", "round", "sin", "cos"),
]
_BINARY = ["mod", "atan2"]
_OVER = ["min", "max", "mean", "sum", "hypot"]
_JOINS = [" + ", " - ", " * ", " / ", " ^ "]
_NOISE = ["(", ")", ",", " and ", " or ", " not ", " < ", " == ", "=", "$", "min("]
_COMPARISONS = ["<", "<=", ">", ">=", "==", "!="]
# The numbers guards compare with; the rows of the guard test land on them.
_EDGES = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0]


def _guard(rng, depth=0):
    """A condition the range analysis narrows on: features against numbers,
    on either side, joined by and, or and not."""
    roll = rng.random()
    if depth > 1 or roll < 0.55:
        name, sign = rng.choice("abc"), rng.choice(_COMPARISONS)
        number = f"{rng.choice(_EDGES):g}"
        return f"{number} {sign} {name}" if roll < 0.15 else f"{name} {sign} {number}"
    if roll < 0.7:
        return f"not ({_guard(rng, depth + 1)})"
    joined = rng.choice(["and", "or"])
    return f"({_guard(rng, depth + 1)} {joined} {_guard(rng, depth + 1)})"


def _formula(rng, depth=0):
    roll = rng.random()
    if depth > 4 or roll < 0.3:
        return rng.choice(_ATOMS)
    if roll < 0.45:
        return f"{rng.choice(_UNARY)}({_formula(rng, depth + 1)})"
    if roll < 0.52:
        args = ", ".join(_formula(rng, depth + 1) for _ in range(rng.randint(2, 3)))
        return f"{rng.choice(_OVER)}({args})"
    if roll < 0.55:
        pair = f"{_formula(rng, depth + 1)}, {_formula(rng, depth + 1)}"
        return f"{rng.choice(_BINARY)}({pair})"
    if roll < 0.6:
        parts = [_formula(rng, depth + 1) for _ in range(3)]
        return f"clip({', '.join(parts)})"
    if roll < 0.65:
        return f"-{_formula(rng, depth + 1)}"
    if roll < 0.72:
        parts = [_formula(rng, depth + 1) for _ in range(4)]
        condition = _guard(rng) if roll < 0.685 else f"{parts[0]} > {parts[1]}"
        return f"if({condition}, {parts[2]}, {parts[3]})"
    if roll < 0.8:
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
        # A value outside a function's domain never comes unannounced.
        assert failure.reason != "out_of_domain" or analysis.warnings + analysis.errors
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


def test_guards_narrow_ranges_without_losing_a_value():
    """Rows sit on the numbers the guards compare with, where narrowing is exact."""
    rng = random.Random(20261111)
    bounds = {"a": (-2.0, 3.0), "b": (0.0, 1.0), "c": (None, None)}

    def pick(low, high):
        inside = [edge for edge in _EDGES if low <= edge <= high]
        return rng.choice([low, high, *inside, rng.uniform(low, high)])

    narrowed = evaluated = skips = 0
    for index in range(1500):
        condition = index % 4 == 0
        text = (
            f"if({_guard(rng)}, {_formula(rng, 2)}, {_formula(rng, 2)}) "
            f"{rng.choice(_COMPARISONS)} {_formula(rng, 3)}"
            if condition
            else f"if({_guard(rng)}, {_formula(rng, 2)}, {_formula(rng, 2)})"
        )
        try:
            expression = parse(text, condition=condition)
            expression.check_names(["a", "b", "c"])
        except FormulaError:
            continue
        analysis = analyze(expression, bounds)
        narrowed += 1
        for _ in range(8):
            row = {
                "a": pick(-2.0, 3.0),
                "b": pick(0.0, 1.0),
                "c": rng.choice([-1e6, 1e6, rng.gauss(0, 10), *_EDGES]),
            }
            if _checked(expression, analysis, row, condition, text):
                evaluated += 1
            else:
                skips += 1
    assert narrowed > 1000 and evaluated > 5000 and skips > 100
