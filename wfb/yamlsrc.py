"""YAML loading that keeps source spans attached to the parsed document.

ruamel's round-trip loader annotates every mapping and sequence with an ``lc``
object holding the 0-based line/column of each key, value and item.  We keep the
``CommentedMap``/``CommentedSeq`` objects themselves as the document -- they are
``dict``/``list`` subclasses, so ``jsonschema`` and ordinary attribute access work
unchanged -- and use :func:`span` to recover a location whenever we need to
report against one.

Round-tripping (ADR 0002's lossless-GUI requirement) is a property of the same
loader, so the compiler and the future editor cannot disagree about the file.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError

from .diagnostics import Bag, Span


class YamlDocument:
    """A parsed YAML file plus the machinery to locate any node inside it."""

    def __init__(self, path: Path, text: str, data: Any) -> None:
        self.path = path
        self.text = text
        self.data = data

    # -- span lookup ------------------------------------------------------

    def span(self, node: Any, key: Any = None, *, of: str = "value") -> Span | None:
        """Locate ``node``, or ``node[key]`` when a key or index is given.

        ``of="key"`` locates the mapping key rather than its value, which is the
        right anchor for "unknown key" style diagnostics.
        """
        lc = getattr(node, "lc", None)
        if lc is None:
            return None
        if key is None:
            return Span(self.path, lc.line + 1, lc.col + 1)
        try:
            if isinstance(key, int) and not isinstance(node, dict):
                pos = lc.item(key)
            elif of == "key":
                pos = lc.key(key)
            else:
                pos = lc.value(key)
        except (KeyError, IndexError, AttributeError, TypeError):
            return Span(self.path, lc.line + 1, lc.col + 1)
        return Span.from_ruamel(self.path, pos)

    def span_for_path(self, parts: list[Any]) -> Span | None:
        """Locate a node addressed by a jsonschema-style path of keys/indices."""
        node = self.data
        span = self.span(node)
        for part in parts:
            try:
                child_span = self.span(node, part)
            except Exception:
                child_span = None
            if child_span is not None:
                span = child_span
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                break
        return span


def load(path: Path, bag: Bag) -> YamlDocument | None:
    """Parse ``path``.  Reports a diagnostic and returns ``None`` on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        bag.error("io", f"cannot read {path}: {exc.strerror}")
        return None
    bag.register_source(path, text)

    yaml = YAML()  # round-trip mode: preserves order, comments and anchors
    try:
        data = yaml.load(io.StringIO(text))
    except MarkedYAMLError as exc:
        mark = exc.problem_mark
        span = Span(path, mark.line + 1, mark.column + 1) if mark else None
        bag.error("yaml", (exc.problem or "invalid YAML").strip(), span)
        return None

    if data is None:
        bag.error("yaml", "the document is empty", Span(path, 1, 1))
        return None
    return YamlDocument(path, text, data)


def dump(data: Any) -> str:
    """Serialise back to YAML, preserving what the loader preserved."""
    yaml = YAML()
    yaml.preserve_quotes = True
    buf = io.StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()
