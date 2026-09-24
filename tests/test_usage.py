"""`wfb.emit.usage` (plan 19 A3): what generated Monkey C actually calls,
read off the emitted text itself rather than re-derived from the IR --
comment/string stripping, barrel-module detection and its closure over
runtime-lib, and `Toybox` module detection."""

from __future__ import annotations

import pytest

from wfb.emit import usage


# -- stripping comments and strings -----------------------------------------


def test_line_comments_are_blanked_including_doc_comments():
    text = "// WfbFoo.bar() is only a comment\n//! WfbFoo.bar() a doc comment too\nreal code"
    stripped = usage.strip_comments_and_strings(text)
    assert "WfbFoo" not in stripped
    assert "real code" in stripped


def test_string_literals_are_blanked():
    text = 'var s = "WfbFoo.bar() inside a string";\nWfbReal.call();'
    stripped = usage.strip_comments_and_strings(text)
    assert "WfbFoo" not in stripped
    assert "WfbReal.call();" in stripped


def test_an_escaped_quote_does_not_end_the_string():
    text = r'var s = "she said \"hi\" // not a comment"; WfbReal.call();'
    stripped = usage.strip_comments_and_strings(text)
    # The whole string, escaped quotes and all, is blanked as one literal --
    # if the escape were mishandled, the string would end early at \" and
    # leave "hi\" // not a comment"; behind as real (uncommented) text.
    assert "hi" not in stripped
    assert "not a comment" not in stripped
    assert "WfbReal.call();" in stripped


def test_a_comment_marker_inside_a_string_is_not_a_comment():
    text = 'var s = "http://example.com"; WfbReal.call();'
    stripped = usage.strip_comments_and_strings(text)
    assert "example.com" not in stripped
    assert "WfbReal.call();" in stripped


# -- barrel modules -----------------------------------------------------------


def test_wfbx_dot_is_a_use_but_the_bare_name_is_not():
    assert usage.barrel_modules("WfbMath.percent(a, b);") == {"WfbMath.mc"}
    assert usage.barrel_modules("var WfbMath = 1;") == set()


def test_a_reference_inside_a_comment_or_string_is_not_a_use():
    assert usage.barrel_modules("// WfbMath.percent(a, b)\nreal;") == set()
    assert usage.barrel_modules('var s = "WfbMath.percent(a, b)";') == set()


def test_barrel_modules_accepts_one_string_or_many():
    assert usage.barrel_modules("WfbMath.percent(a, b);") == usage.barrel_modules(
        ["WfbMath.percent(a, b);"]
    )
    assert usage.barrel_modules(["WfbMath.percent(1, 2);", "WfbArc.drawSpan();"]) == {
        "WfbMath.mc", "WfbArc.mc",
    }


def test_an_unknown_barrel_module_is_a_clear_compiler_bug_error():
    """A generated call into a module that was never written is a compiler
    bug, not something a build should silently drop -- see
    `wfb.emit.usage.UnknownBarrelModule`'s own docstring."""
    with pytest.raises(usage.UnknownBarrelModule, match="WfbNope"):
        usage.barrel_modules("WfbNope.thing();")


def test_the_closure_reaches_a_barrel_file_that_calls_another(tmp_path, monkeypatch):
    """No barrel file references another one today, but the closure must
    not depend on that staying true -- proven here by pointing the scanner
    at a temporary runtime-lib directory where one does."""
    (tmp_path / "WfbOuter.mc").write_text("module WfbOuter { function f() { WfbInner.g(); } }")
    (tmp_path / "WfbInner.mc").write_text("module WfbInner { function g() {} }")
    monkeypatch.setattr(usage, "RUNTIME_LIB", tmp_path)
    assert usage.barrel_modules("WfbOuter.f();") == {"WfbOuter.mc", "WfbInner.mc"}


def test_no_runtime_lib_file_references_another_today():
    """The closure exists for the future, not because it fires today -- every
    installed barrel file's own direct references resolve to itself only."""
    for path in sorted(usage.RUNTIME_LIB.glob("*.mc")):
        direct = usage._direct_barrel_files(path.read_text(encoding="utf-8"))
        assert direct <= {path.name}, f"{path.name} calls into {direct - {path.name}}"


# -- Toybox modules -----------------------------------------------------------


def test_a_dotted_reference_is_detected():
    assert usage.toybox_modules("var w as Weather.CurrentConditions? = null;") == {
        "Toybox.Weather",
    }


def test_a_bare_has_check_is_detected():
    """`:WatchFaceConfig` on its own right of `has` is a Symbol literal, not
    a `WatchFaceConfig.` member reference -- `Application` is the only
    module this line by itself asks for; `WatchFaceConfig.` gets its own
    import only where the generated code actually dereferences it (the next
    test), the same way the real view's `onLayout` guard and its
    `applyConfig` body are two separate lines."""
    assert usage.toybox_modules("if (Application has :WatchFaceConfig) { }") == {
        "Toybox.Application",
    }


def test_watchfaceconfig_dot_is_the_nested_module():
    assert usage.toybox_modules("WatchFaceConfig.getSettings(null);") == {
        "Toybox.Application.WatchFaceConfig",
    }


def test_gregorian_dot_is_the_nested_time_module():
    assert usage.toybox_modules("Gregorian.info(Time.now(), Time.FORMAT_MEDIUM);") == {
        "Toybox.Time.Gregorian", "Toybox.Time",
    }


def test_a_type_annotation_counts_as_a_reference():
    text = "private function f(activity as ActivityMonitor.Info) as Void {}"
    assert usage.toybox_modules(text) == {"Toybox.ActivityMonitor"}


def test_a_module_mentioned_only_in_a_comment_or_string_is_not_detected():
    assert usage.toybox_modules("// Weather.getCurrentConditions()\nreal;") == set()
    assert usage.toybox_modules('var s = "Weather.getCurrentConditions()";') == set()


def test_a_similarly_named_identifier_is_not_a_false_positive():
    """`\\b` word boundaries: a longer identifier that merely starts with a
    known module name is not mistaken for a reference to it."""
    assert usage.toybox_modules("var mySystemState = 1;") == set()
    assert usage.toybox_modules("var ActivityMonitorFoo = 1;") == set()


def test_no_modules_found_returns_an_empty_set():
    assert usage.toybox_modules("dc.drawText(0, 0, font, text, justify);") == set()
