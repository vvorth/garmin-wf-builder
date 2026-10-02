"""The editor's patch engine: pure text in, text out.

The design's text is the only document (ADR 0002). Every edit, from a
canvas drag, an inspector field or a structural action, is a patch that
rewrites some characters of that text and leaves every other byte alone:

- `spans`: the span index, every `key: value` entry with its character
  range, and each element found by its `Element.span`;
- `patch`: scalar and structural patches (set, add or remove a key;
  delete, duplicate, move or add an element);
- `gate`: what a patch must pass to be accepted -- it parses to exactly
  the intended data and loads with no new error;
- `geometry`: a pixel drag on one device, written in the author's units to
  the key that device reads (the override target).

There is no server here: text in, text out.
"""

from .gate import Gate, Loaded, load_text
from .geometry import Converted, View, move, resize, target
from .patch import (
    Patch, add_element, delete_element, duplicate_element, move_element, remove, set_value,
)
from .spans import Entry, Refused, SpanIndex, parse

__all__ = [
    "Converted", "Entry", "Gate", "Loaded", "Patch", "Refused", "SpanIndex", "View",
    "add_element", "delete_element", "duplicate_element", "load_text", "move", "move_element",
    "parse", "remove", "resize", "set_value", "target",
]
