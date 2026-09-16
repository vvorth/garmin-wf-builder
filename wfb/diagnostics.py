"""Diagnostics carrying YAML source spans.

ADR 0002 requires every error to point at the author's YAML, with file, line and
column -- not at an internal representation.  ADR 0008 requires each diagnostic
to carry a severity and, where the check rests on estimation, to say so.
"""

from __future__ import annotations

import sys
import textwrap
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import term
from .term import SEVERITY_STYLE

#: Visible width of the "      note: " label, shared by the first line and
#: the hanging indent every continuation line lines up under.
_NOTE_PREFIX = "      note: "
_NOTE_INDENT = " " * len(_NOTE_PREFIX)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


#: Bag.render order: notes first, then warnings, then errors, so the most
#: important items end up next to the summary printed after them.
_RENDER_ORDER = {Severity.NOTE: 0, Severity.WARNING: 1, Severity.ERROR: 2}


@dataclass(frozen=True)
class Span:
    """A location in a source file.  ``line`` and ``col`` are 1-based."""

    path: Path
    line: int
    col: int

    @classmethod
    def from_ruamel(cls, path: Path, lc: tuple[int, int] | None) -> "Span | None":
        """Build a span from ruamel's 0-based ``(line, col)`` pair."""
        if lc is None:
            return None
        return cls(path, lc[0] + 1, lc[1] + 1)

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}"


@dataclass
class Diagnostic:
    severity: Severity
    code: str
    message: str
    span: Span | None = None
    #: Free-form follow-up lines: suggestions, the legal alternatives, etc.
    notes: list[str] = field(default_factory=list)
    #: Set when the finding rests on estimation rather than measurement
    #: (ADR 0008 -- checks that must not overclaim).
    confidence: str | None = None

    def render(
        self,
        source_lines: dict[Path, list[str]] | None = None,
        *,
        color: bool = False,
        width: int | None = None,
        notes_as: str | None = None,
    ) -> str:
        """Render one diagnostic.

        With the defaults this is plain text -- no ANSI -- so existing
        callers such as ``bag.render()`` in tests keep working unchanged.
        ``notes_as``, when given, replaces the notes/confidence block with a
        single collapsed-note line reading ``notes_as`` (Bag.render's way of
        not repeating an identical note block for every target device).
        """
        sev_styles = SEVERITY_STYLE[self.severity.value]
        if self.span:
            path_str = term.style(str(self.span.path), "bold", enabled=color)
            head = f"{path_str}:{self.span.line}:{self.span.col}: "
        else:
            head = ""
        sev_str = term.style(self.severity.value, *sev_styles, enabled=color)
        code_str = term.style(f"[{self.code}]", "dim", enabled=color)
        msg_str = term.style(self.message, "bold", enabled=color)
        out = [f"{head}{sev_str}{code_str}: {msg_str}"]
        if self.span and source_lines:
            lines = source_lines.get(self.span.path)
            if lines and 0 < self.span.line <= len(lines):
                text = lines[self.span.line - 1].rstrip("\n")
                gutter = f"{self.span.line:>5} | "
                gutter_str = term.style(gutter, "dim", enabled=color)
                out.append(f"{gutter_str}{text}")
                caret = term.style("^", *sev_styles, enabled=color)
                out.append(" " * len(gutter) + " " * (self.span.col - 1) + caret)
        if notes_as is not None:
            label = term.style("note:", "bold", "cyan", enabled=color)
            out.append(f"      {label} {notes_as}")
        else:
            for note in self.notes:
                out.extend(_render_note(note, color=color, width=width))
            if self.confidence:
                label = term.style("confidence:", "dim", enabled=color)
                out.append(f"      {label} {self.confidence}")
        return "\n".join(out)


def _render_note(note: str, *, color: bool, width: int | None) -> list[str]:
    """Render one ``note:`` entry, wrapping its prose when ``width`` is given.

    A note with its own explicit newlines is a snippet, not prose -- it is
    printed as-is, one output line per source line, and never rewrapped,
    even when ``width`` is given.  A single-line note is word-wrapped to
    ``width`` with a hanging indent, so continuation lines line up under the
    note's own text rather than under the ``note:`` label.
    """
    label = term.style("note:", "bold", "cyan", enabled=color)
    if "\n" in note or not width:
        first, *rest = note.splitlines() or [""]
        out = [f"      {label} {first}"]
        out.extend(f"{_NOTE_INDENT}{line}" for line in rest)
        return out
    wrap_width = max(1, width - len(_NOTE_PREFIX))
    wrapped = textwrap.wrap(note, width=wrap_width) or [""]
    out = [f"      {label} {wrapped[0]}"]
    out.extend(f"{_NOTE_INDENT}{line}" for line in wrapped[1:])
    return out


class Bag:
    """Collects diagnostics across a build and decides whether it may proceed."""

    def __init__(self) -> None:
        self.items: list[Diagnostic] = []
        self._sources: dict[Path, list[str]] = {}

    def register_source(self, path: Path, text: str) -> None:
        self._sources[path] = text.splitlines()

    def add(self, diag: Diagnostic) -> Diagnostic:
        self.items.append(diag)
        return diag

    def error(self, code: str, message: str, span: Span | None = None, **kw) -> Diagnostic:
        return self.add(Diagnostic(Severity.ERROR, code, message, span, **kw))

    def warning(self, code: str, message: str, span: Span | None = None, **kw) -> Diagnostic:
        return self.add(Diagnostic(Severity.WARNING, code, message, span, **kw))

    def note(self, code: str, message: str, span: Span | None = None, **kw) -> Diagnostic:
        return self.add(Diagnostic(Severity.NOTE, code, message, span, **kw))

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.ERROR]

    def ok(self) -> bool:
        return not self.errors

    def render(self, *, color: bool = False, width: int | None = None) -> str:
        """Render every diagnostic, most important last, next to the summary.

        Diagnostics are ordered notes, then warnings, then errors (stable
        within a severity; ``self.items`` itself is not reordered) and
        separated by one blank line.  A diagnostic whose ``(code, notes,
        confidence)`` exactly repeats one already rendered earlier in this
        same call -- the same warning against every target device, say --
        is rendered once in full; later repeats collapse to their header,
        source excerpt and a single "same notes as the earlier [...] above"
        line, so a 50-diagnostic build is not a wall of repeated text.
        """
        ordered = sorted(self.items, key=lambda d: _RENDER_ORDER[d.severity])
        seen: set[tuple[str, tuple[str, ...], str | None]] = set()
        pieces = []
        for d in ordered:
            key = (d.code, tuple(d.notes), d.confidence)
            notes_as = None
            if (d.notes or d.confidence) and key in seen:
                notes_as = f"same notes as the earlier [{d.code}] above"
            else:
                seen.add(key)
            pieces.append(d.render(self._sources, color=color, width=width, notes_as=notes_as))
        return "\n\n".join(pieces)

    def print(self, stream=sys.stderr) -> None:
        if self.items:
            print(self.render(color=term.should_color(stream), width=term.width(stream)), file=stream)

    def summary(self, *, color: bool = False) -> str:
        n_e = sum(1 for d in self.items if d.severity is Severity.ERROR)
        n_w = sum(1 for d in self.items if d.severity is Severity.WARNING)
        n_n = sum(1 for d in self.items if d.severity is Severity.NOTE)
        parts = []
        if n_e:
            text = f"{n_e} error{'s' if n_e != 1 else ''}"
            parts.append(term.style(text, *SEVERITY_STYLE["error"], enabled=color))
        if n_w:
            text = f"{n_w} warning{'s' if n_w != 1 else ''}"
            parts.append(term.style(text, *SEVERITY_STYLE["warning"], enabled=color))
        if n_n:
            text = f"{n_n} note{'s' if n_n != 1 else ''}"
            parts.append(term.style(text, *SEVERITY_STYLE["note"], enabled=color))
        return ", ".join(parts) if parts else "no diagnostics"
