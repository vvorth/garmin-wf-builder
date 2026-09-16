"""Readable, coloured diagnostic rendering.

Covers `Diagnostic.render`/`Bag.render`'s colour, wrapping and de-duplication
behaviour (the "wall of text" problems this was written to fix), plus
`term.should_color`'s precedence order, which both `Bag.print` and the CLI
rely on.
"""

from __future__ import annotations

import pytest

from wfb import term
from wfb.diagnostics import Bag, Diagnostic, Severity, Span


@pytest.fixture(autouse=True)
def _reset_term_mode():
    # `term.set_mode` is process-wide state; do not leak it into other tests.
    yield
    term.set_mode("auto")


class FakeStream:
    """A minimal stream stand-in with a controllable `isatty()`."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# --- plain vs coloured -------------------------------------------------


def test_plain_render_has_no_ansi_escapes():
    bag = Bag()
    bag.error("bad-thing", "something is wrong")
    bag.warning("meh", "a minor issue", notes=["consider X"])
    text = bag.render()
    assert "\033" not in text


def test_colour_render_contains_ansi_and_still_the_severity_codes():
    bag = Bag()
    bag.error("bad-thing", "something is wrong")
    bag.warning("meh", "a minor issue")
    text = bag.render(color=True)
    assert "\033[" in text
    assert "[bad-thing]" in text
    assert "[meh]" in text


def test_header_styling_path_severity_code_message(tmp_path):
    path = tmp_path / "face.yaml"
    path.write_text("a: 1\nb: 2\n")
    bag = Bag()
    bag.register_source(path, path.read_text())
    bag.error("bad-thing", "boom", span=Span(path, 2, 3))
    text = bag.render(color=True)

    path_styled = term.style(str(path), "bold", enabled=True)
    sev_styled = term.style("error", *term.SEVERITY_STYLE["error"], enabled=True)
    code_styled = term.style("[bad-thing]", "dim", enabled=True)
    msg_styled = term.style("boom", "bold", enabled=True)
    assert path_styled in text
    assert sev_styled in text
    assert code_styled in text
    assert msg_styled in text


def test_source_excerpt_gutter_dim_and_caret_severity_coloured(tmp_path):
    path = tmp_path / "face.yaml"
    path.write_text("a: 1\nb: 2\n")
    bag = Bag()
    bag.register_source(path, path.read_text())
    bag.error("e", "bad", span=Span(path, 2, 3))
    text = bag.render(color=True)

    gutter_styled = term.style("    2 | ", "dim", enabled=True)
    caret_styled = term.style("^", *term.SEVERITY_STYLE["error"], enabled=True)
    assert gutter_styled in text
    assert caret_styled in text


# --- blank-line separation and severity ordering ------------------------


def test_blank_line_separates_diagnostics():
    bag = Bag()
    bag.error("e1", "first")
    bag.error("e2", "second")
    text = bag.render()
    pieces = text.split("\n\n")
    assert len(pieces) == 2
    # no diagnostic itself contains a blank line, so this is a clean split
    assert all(piece.strip() for piece in pieces)


def test_severity_ordering_notes_then_warnings_then_errors():
    bag = Bag()
    bag.error("e", "an error")
    bag.warning("w", "a warning")
    bag.note("n", "a note")
    text = bag.render()
    assert text.index("note[n]") < text.index("warning[w]") < text.index("error[e]")
    # bag.items itself must stay in insertion order -- render() must not
    # reorder the underlying list, only its own output.
    assert [d.severity for d in bag.items] == [Severity.ERROR, Severity.WARNING, Severity.NOTE]


# --- repeated-note collapsing -------------------------------------------


def test_repeated_identical_notes_collapse_to_one_reference_line():
    bag = Bag()
    bag.warning("dup", "on device A", notes=["do X", "do Y"], confidence="estimate")
    bag.warning("dup", "on device B", notes=["do X", "do Y"], confidence="estimate")
    bag.warning("dup", "on device C", notes=["do X", "do Y"], confidence="estimate")
    text = bag.render()
    assert text.count("do X") == 1
    assert text.count("do Y") == 1
    assert text.count("estimate") == 1
    assert text.count("same notes as the earlier [dup] above") == 2
    # all three headers still appear -- only the note block collapses
    assert text.count("warning[dup]") == 3


def test_notes_that_differ_are_not_collapsed():
    bag = Bag()
    bag.warning("dup", "on device A", notes=["do X"])
    bag.warning("dup", "on device B", notes=["do Z"])
    text = bag.render()
    assert "do X" in text and "do Z" in text
    assert "same notes as the earlier" not in text


def test_bare_duplicates_with_no_notes_or_confidence_are_not_collapsed():
    bag = Bag()
    bag.warning("w", "identical message")
    bag.warning("w", "identical message")
    text = bag.render()
    assert "same notes as the earlier" not in text
    assert text.count("warning[w]") == 2


def test_different_codes_with_identical_notes_are_not_collapsed():
    bag = Bag()
    bag.warning("a", "message one", notes=["shared note"])
    bag.warning("b", "message two", notes=["shared note"])
    text = bag.render()
    assert text.count("shared note") == 2
    assert "same notes as the earlier" not in text


# --- wrapping -------------------------------------------------------------


def test_note_wraps_at_width_with_hanging_indent():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    diag = Diagnostic(Severity.WARNING, "w", "msg", notes=[words])
    text = diag.render(width=30)
    lines = text.splitlines()
    note_lines = lines[1:]
    assert len(note_lines) > 1, "expected the long note to wrap across multiple lines"
    assert note_lines[0].startswith("      note: ")
    for line in note_lines:
        assert len(line) <= 30
    for line in note_lines[1:]:
        assert line.startswith(" " * 12)
        assert line[12] != " "  # hanging indent, not extra padding

    # no words lost or reordered by wrapping
    first_content = note_lines[0][len("      note: "):]
    rest_content = [line[12:] for line in note_lines[1:]]
    reconstructed = " ".join([first_content, *rest_content])
    assert reconstructed.split() == words.split()


def test_note_without_width_is_not_wrapped():
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
    diag = Diagnostic(Severity.WARNING, "w", "msg", notes=[words])
    text = diag.render()
    lines = text.splitlines()
    assert len(lines) == 2
    assert lines[1] == f"      note: {words}"


def test_note_explicit_newlines_are_preserved_and_never_rewrapped():
    snippet = "suggested fix:\n    color: palette.fg\n    size: 10px"
    diag = Diagnostic(Severity.WARNING, "w", "msg", notes=[snippet])
    text = diag.render(width=10)  # deliberately narrow: would force-wrap prose
    lines = text.splitlines()
    assert lines[1] == "      note: suggested fix:"
    assert lines[2] == " " * 12 + "    color: palette.fg"
    assert lines[3] == " " * 12 + "    size: 10px"


# --- Bag.summary colouring -------------------------------------------------


def test_summary_plain_is_unstyled():
    bag = Bag()
    bag.error("e", "boom")
    bag.warning("w", "meh")
    text = bag.summary()
    assert "\033" not in text
    assert text == "1 error, 1 warning"


def test_summary_colour_styles_each_count_by_severity():
    bag = Bag()
    bag.error("e", "boom")
    bag.warning("w", "meh")
    bag.note("n", "fyi")
    text = bag.summary(color=True)
    assert term.style("1 error", *term.SEVERITY_STYLE["error"], enabled=True) in text
    assert term.style("1 warning", *term.SEVERITY_STYLE["warning"], enabled=True) in text
    assert term.style("1 note", *term.SEVERITY_STYLE["note"], enabled=True) in text


# --- term.should_color precedence -----------------------------------------


def test_should_color_precedence(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    term.set_mode("auto")

    tty = FakeStream(True)
    plain = FakeStream(False)

    # 4. TTY and TERM != dumb, by default
    assert term.should_color(tty) is True
    assert term.should_color(plain) is False

    monkeypatch.setenv("TERM", "dumb")
    assert term.should_color(tty) is False
    monkeypatch.delenv("TERM")

    # 3. FORCE_COLOR/CLICOLOR_FORCE beat a non-TTY
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert term.should_color(plain) is True
    monkeypatch.delenv("FORCE_COLOR")

    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert term.should_color(plain) is True
    monkeypatch.delenv("CLICOLOR_FORCE")

    # 2. NO_COLOR beats FORCE_COLOR and a TTY
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert term.should_color(tty) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.delenv("FORCE_COLOR")

    # 1. --color always|never (set_mode) beats everything else
    term.set_mode("always")
    assert term.should_color(plain) is True
    term.set_mode("never")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert term.should_color(tty) is False
    monkeypatch.delenv("FORCE_COLOR")
    term.set_mode("auto")
