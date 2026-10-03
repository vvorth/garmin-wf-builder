"""The editor's patch engine: pure text in, text out.

The design's text is the only document (ADR 0002). Every edit, from a
canvas drag, an inspector field or a structural action, is a patch that
rewrites some characters of that text and leaves every other byte alone:

- `spans`: the span index, every `key: value` entry with its character
  range, and each element found by its `Element.span`;
- `patch`: scalar and structural patches (set a value, block or flow; add,
  remove or rename a key; rewrite references to a renamed name; delete,
  duplicate, move or add an element);
- `gate`: what a patch must pass to be accepted -- it parses to exactly
  the intended data and loads with no new error;
- `geometry`: a pixel drag on one device, written in the author's units to
  the key that device reads (the override target);
- `structure`: an element moved between blocks (static and dynamic, a
  layout's, a group's), grouped and ungrouped, and new elements of every
  type.

There is no server here: text in, text out.
"""

from .gate import Gate, Loaded, load_text
from .geometry import Converted, View, move, resize, target, turn
from .patch import (
    Patch, add_element, chain, delete_element, duplicate_element, move_element, remove,
    remove_slot, rename_key, rename_reference, rename_slot, rewrite_scalars, set_value,
)
from .spans import Entry, Refused, SpanIndex, parse
from .structure import add, element_types, group, move_to_block, ungroup

__all__ = [
    "Converted", "Entry", "Gate", "Loaded", "Patch", "Refused", "SpanIndex", "View",
    "add_element", "chain", "delete_element", "duplicate_element", "load_text", "move",
    "move_element", "parse", "remove", "remove_slot", "rename_key", "rename_reference", "rename_slot",
    "resize",
    "rewrite_scalars", "set_value", "target", "turn",
    "add", "element_types", "group", "move_to_block", "ungroup",
]
