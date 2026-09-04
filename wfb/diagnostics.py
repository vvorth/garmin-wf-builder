"""Diagnostics carrying YAML source spans.

ADR 0002 requires every error to point at the author's YAML, with file, line and
column -- not at an internal representation.  ADR 0008 requires each diagnostic
to carry a severity and, where the check rests on estimation, to say so.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


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

    def render(self, source_lines: dict[Path, list[str]] | None = None) -> str:
        head = f"{self.span}: " if self.span else ""
        out = [f"{head}{self.severity.value}[{self.code}]: {self.message}"]
        if self.span and source_lines:
            lines = source_lines.get(self.span.path)
            if lines and 0 < self.span.line <= len(lines):
                text = lines[self.span.line - 1].rstrip("\n")
                gutter = f"{self.span.line:>5} | "
                out.append(f"{gutter}{text}")
                out.append(" " * len(gutter) + " " * (self.span.col - 1) + "^")
        for note in self.notes:
            first, *rest = note.splitlines() or [""]
            out.append(f"      note: {first}")
            # Continuation lines line up under the note's text, so a multi-line
            # note -- a suggested snippet, usually -- reads as one block.
            out.extend(f"            {line}" for line in rest)
        if self.confidence:
            out.append(f"      confidence: {self.confidence}")
        return "\n".join(out)


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

    def render(self) -> str:
        return "\n".join(d.render(self._sources) for d in self.items)

    def print(self, stream=sys.stderr) -> None:
        if self.items:
            print(self.render(), file=stream)

    def summary(self) -> str:
        n_e = sum(1 for d in self.items if d.severity is Severity.ERROR)
        n_w = sum(1 for d in self.items if d.severity is Severity.WARNING)
        n_n = sum(1 for d in self.items if d.severity is Severity.NOTE)
        parts = []
        if n_e:
            parts.append(f"{n_e} error{'s' if n_e != 1 else ''}")
        if n_w:
            parts.append(f"{n_w} warning{'s' if n_w != 1 else ''}")
        if n_n:
            parts.append(f"{n_n} note{'s' if n_n != 1 else ''}")
        return ", ".join(parts) if parts else "no diagnostics"


class BuildError(Exception):
    """Raised to abort a build once errors have been reported."""
