"""The expression language: parsing, typing, folding and Monkey C emission."""

import pytest

from wfb.catalog import Type
from wfb.expr import (
    Binding, ExprError, Scope, Value, compile_expression, evaluate, parse,
)


@pytest.fixture
def scope():
    s = Scope()
    s.define("activity.steps", Binding(Value(Type.NUMBER, True), "activitySteps"))
    s.define("activity.step_goal", Binding(Value(Type.NUMBER, True), "activityStepGoal"))
    s.define("system.battery", Binding(Value(Type.FLOAT), "systemBattery"))
    s.define("device.phone_connected", Binding(Value(Type.BOOLEAN), "devicePhoneConnected"))
    s.define("palette.hot", Binding(Value(Type.COLOR), "Palette.HOT", constant=0xFF5500))
    s.define("palette.text", Binding(Value(Type.COLOR), "Palette.TEXT", constant=0xFFFFFF))
    return s


@pytest.mark.parametrize("text,code", [
    ("activity.steps", "activitySteps"),
    ("2 * 3 + 4", "10"),
    ("system.battery / 2", "(systemBattery / 2)"),
    ("min(activity.steps, 10000)", "WfbMath.min(activitySteps, 10000)"),
    ("percent(activity.steps, activity.step_goal)",
     "WfbMath.percent(activitySteps, activityStepGoal)"),
    ("round(system.battery)", "Math.round(systemBattery).toNumber()"),
    ("not device.phone_connected", "(!devicePhoneConnected)"),
    ("device.phone_connected and true", "(devicePhoneConnected && true)"),
])
def test_emission(scope, text, code):
    assert compile_expression(text, scope)[0] == code


def test_constants_fold_at_build_time(scope):
    """Only genuinely dynamic terms survive into the generated code."""
    code, _, _ = compile_expression("clamp(2 + 3, 0, 100) * 2", scope)
    assert code == "10"


def test_palette_references_stay_named(scope):
    """Inlining the hex would throw away the whole point of having a palette."""
    code, value, _ = compile_expression(
        "activity.steps > activity.step_goal ? palette.hot : palette.text", scope
    )
    assert code == "((activitySteps > activityStepGoal) ? Palette.HOT : Palette.TEXT)"
    assert value.type is Type.COLOR


def test_nullability_propagates(scope):
    assert compile_expression("activity.steps + 1", scope)[1].nullable is True
    assert compile_expression("system.battery + 1", scope)[1].nullable is False


def test_division_always_yields_a_float(scope):
    assert compile_expression("4 / 2", scope)[1].type is Type.FLOAT


def test_integer_division_is_coerced_to_float_in_the_emitted_code(scope):
    """`check` types `/` as Float unconditionally, but Monkey C's own
    `Number / Number` truncates -- unlike `4 / 2` above (which folds to a
    build-time constant and never reaches this code at all), a genuinely
    dynamic Number/Number division must have the emitted Monkey C coerce one
    side, or the device silently disagrees with the host-side preview, which
    evaluates the same expression with Python's true division."""
    code, value, _ = compile_expression("activity.steps / 1000", scope)
    assert code == "(activitySteps.toFloat() / 1000)"
    assert value.type is Type.FLOAT


def test_division_with_an_already_float_operand_is_left_alone(scope):
    """Monkey C promotes a Number/Float mix to Float on its own -- adding
    `.toFloat()` here would be redundant, not incorrect, but it would also be
    noise the generated code doesn't need (ADR 0003)."""
    code, _, _ = compile_expression("system.battery / 2", scope)
    assert code == "(systemBattery / 2)"
    assert ".toFloat()" not in code


def test_division_by_a_literal_float_needs_no_coercion(scope):
    """The mirror image of the case above, with the Float on the right --
    e.g. `activity.distance / 100000.0` in examples/dashboard/face.yaml."""
    code, _, _ = compile_expression("activity.steps / 100000.0", scope)
    assert code == "(activitySteps / 100000.0f)"
    assert ".toFloat()" not in code


def test_constant_division_folds_before_coercion_would_apply(scope):
    """A build-time-constant division becomes a plain Float literal (Python
    true division at fold time) and never reaches the Binary-emission code
    that adds `.toFloat()` -- there is nothing left to coerce."""
    code, _, node = compile_expression("10 / 4", scope)
    assert code == "2.5f"
    assert ".toFloat()" not in code


def test_integer_division_of_a_bare_literal_parenthesizes_before_tofloat(scope):
    """`5.toFloat()` is not a method call in Monkey C -- the lexer reads `5.`
    as the start of a malformed decimal literal -- so a bare numeric literal
    operand must be parenthesized first: `(5).toFloat()`."""
    code, _, _ = compile_expression("10 / activity.steps", scope)
    assert code == "((10).toFloat() / activitySteps)"


def test_modulo_is_not_affected_by_the_division_fix(scope):
    assert compile_expression("activity.steps % 7", scope)[0] == "(activitySteps % 7)"


def test_unknown_source_suggests_the_nearest_catalogue_entry(scope):
    with pytest.raises(ExprError) as excinfo:
        compile_expression("activity.stps", scope)
    assert "activity.steps" in " ".join(excinfo.value.notes)


def test_colour_arithmetic_is_rejected(scope):
    """A colour is not a number; arithmetic on one is almost always a mistake."""
    with pytest.raises(ExprError) as excinfo:
        compile_expression("palette.hot + 1", scope)
    assert "color" in excinfo.value.message


def test_ternary_condition_must_be_boolean(scope):
    with pytest.raises(ExprError):
        compile_expression("1 ? 2 : 3", scope)


def test_ternary_branches_must_agree(scope):
    with pytest.raises(ExprError):
        compile_expression("device.phone_connected ? palette.hot : 5", scope)


def test_unknown_function_lists_the_whole_set(scope):
    with pytest.raises(ExprError) as excinfo:
        compile_expression("sqrt(4)", scope)
    notes = " ".join(excinfo.value.notes)
    for name in ("min", "max", "clamp", "round", "floor", "abs", "percent"):
        assert name in notes


def test_wrong_arity_is_reported(scope):
    with pytest.raises(ExprError) as excinfo:
        compile_expression("clamp(1, 2)", scope)
    assert "3 argument" in excinfo.value.message


def test_error_offsets_point_into_the_expression(scope):
    with pytest.raises(ExprError) as excinfo:
        compile_expression("1 + palette.hot", scope)
    assert excinfo.value.offset > 0


def test_language_has_no_statements(scope):
    for text in ["var x = 1", "x = 1", "while (true) {}", "function f() {}"]:
        with pytest.raises(ExprError):
            compile_expression(text, scope)


# -- host-side evaluation, used only by the preview renderer ----------------


def test_evaluate_matches_the_compiled_semantics(scope):
    node = parse("percent(activity.steps, activity.step_goal)")
    assert evaluate(node, {"activity.steps": 8432, "activity.step_goal": 10000}) == pytest.approx(84.32)


def test_evaluate_propagates_absence(scope):
    node = parse("activity.steps + 1")
    assert evaluate(node, {"activity.steps": None}) is None


def test_percent_of_a_zero_goal_is_zero_not_a_crash(scope):
    """`WfbMath.percent` returns 0.0 for a goal <= 0 (an unset step goal is
    a real reading), so the preview must show 0, not treat it as absent."""
    node = parse("percent(activity.steps, activity.step_goal)")
    assert evaluate(node, {"activity.steps": 100, "activity.step_goal": 0}) == 0.0
    assert evaluate(node, {"activity.steps": 100, "activity.step_goal": -5}) == 0.0


# -- host/device parity (plan 18 items 3-4) ---------------------------------
#
# The host half of every function and operator is what constant folding bakes
# into generated code and what the preview draws, so it must compute exactly
# what the device computes: `Math.round` ("Decimal values >= .5 will be
# rounded up", $CIQ_SDK/doc/Toybox/Math.html), `WfbMath.percent`/`clamp`
# (runtime-lib/WfbMath.mc), and Monkey C's truncating `%`
# (docs/research/probes/math-parity/).


@pytest.mark.parametrize("value,expected", [
    (2.5, 3), (72.5, 73), (0.5, 1), (2.4999, 2), (2.0, 2), (3, 3),
    (0.49999999999999994, 0), (-2.4, -2), (-2.6, -3),
])
def test_round_is_half_up_like_math_round(value, expected):
    assert evaluate(parse("round(x)"), {"x": value}) == expected


def test_round_of_a_half_folds_up(scope):
    assert compile_expression("round(2.5)", scope)[0] == "3"
    assert compile_expression("round(72.5)", scope)[0] == "73"


def test_round_of_a_negative_half_is_left_to_the_device(scope):
    """`Math.round(-2.5)` is -2 under "half up" and -3 under "half away from
    zero"; the SDK does not say which, and no simulator runs here to find
    out. So the build never bakes either answer in: the call stays."""
    assert compile_expression("round(-2.5)", scope)[0] == "Math.round(-2.5f).toNumber()"
    assert compile_expression("round(-2.6)", scope)[0] == "-3"


@pytest.mark.parametrize("steps,goal,expected", [
    (12000, 10000, 100.0),   # over goal: clamped, not 120
    (8432, 10000, 84.32),
    (-50, 100, 0.0),         # clamped at the bottom too
    (100, 0, 0.0),           # zero goal: 0, not absent
])
def test_percent_matches_wfbmath(steps, goal, expected):
    node = parse("percent(activity.steps, activity.step_goal)")
    got = evaluate(node, {"activity.steps": steps, "activity.step_goal": goal})
    assert got == pytest.approx(expected)


def test_constant_percent_folds_clamped(scope):
    assert compile_expression("percent(150, 100)", scope)[0] == "100.0f"
    assert compile_expression("percent(5, 0)", scope)[0] == "0.0f"


def test_clamp_checks_lo_before_hi_like_wfbmath(scope):
    """With lo > hi, `WfbMath.clamp` returns lo for a value below lo and hi
    for one above hi -- `max(lo, min(v, hi))` returned lo for both."""
    assert compile_expression("clamp(50, 10, 0)", scope)[0] == "0"
    assert compile_expression("clamp(5, 10, 0)", scope)[0] == "10"
    assert evaluate(parse("clamp(x, 10, 0)"), {"x": 50}) == 0


@pytest.mark.parametrize("text,expected", [
    ("-7 % 3", "-1"), ("7 % -3", "1"), ("7 % 3", "1"), ("-7 % -3", "-1"),
])
def test_modulo_truncates_like_monkey_c(scope, text, expected):
    """`monkeyc`'s own constant folder turns `-7 % 3` into -1 and `7 % -3`
    into 1 (docs/research/probes/math-parity/): the remainder takes the
    dividend's sign. Python's floor modulo gives 2 and -2."""
    assert compile_expression(text, scope)[0] == expected


def test_modulo_evaluates_truncated_in_the_preview():
    assert evaluate(parse("x % 3"), {"x": -7}) == -1


@pytest.mark.parametrize("text", [
    "system.battery % 10", "activity.steps % 2.5", "7.5 % 2",
])
def test_modulo_on_a_float_is_refused(scope, text):
    """`monkeyc -l 3` rejects `mod` on a Float operand ("Cannot perform
    operation 'mod' on types ... Float and ... Number"), so the design must
    be refused here rather than fail at compile time."""
    with pytest.raises(ExprError, match="%"):
        compile_expression(text, scope)
