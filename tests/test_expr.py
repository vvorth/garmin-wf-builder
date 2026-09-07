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
    s.define("palette.hot", Binding(Value(Type.COLOR), "Palette.HOT", constant=0xFF5500,
                                    kind="palette"))
    s.define("palette.text", Binding(Value(Type.COLOR), "Palette.TEXT", constant=0xFFFFFF,
                                     kind="palette"))
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
    node = parse("percent(activity.steps, activity.step_goal)")
    assert evaluate(node, {"activity.steps": 100, "activity.step_goal": 0}) is None
