"""Structural patches: elements moved between blocks, grouped and
ungrouped, and new elements of every type.

An element block is an id-keyed mapping: the top level's and a layout's
`static:` and `elements:`, and a group's `children:`. Moving an element
between two of them cuts its lines (its leading comments with it, the
rule `SpanIndex.entry_range` follows) and pastes them into the other,
re-indented by the difference between the two blocks' indents. Nothing
inside the element is re-serialised. A block that does not exist yet is
created; one emptied by a move goes, with its key, as `remove` does.

Grouping wraps sibling elements in a new `group` with only `type:` and
`children:`, whose box is its parent's, so nothing moves on the screen.
Ungrouping is the reverse, and is refused for a group with any other key
(`at:`, `visible:`, ...), since its children would lose what it gives
them.
"""

from __future__ import annotations

import copy
from typing import Any

from ruamel.yaml.nodes import MappingNode, ScalarNode

from .patch import (
    DEFAULTS, Patch, _block, _data_at, _ended_patch, _insert_after, _remove, _with,
    face_color, flow, key_text,
)
from .spans import (
    ELEMENT_BLOCKS, Entry, Path, Refused, SpanIndex, dotted, index_for, is_element, line_end,
)

#: The types `add` needs a choice for, and what the choice names.
CHOICES = {"graph": "series", "data": "slot", "hands": "set"}

#: New elements of the types `patch.DEFAULTS` leaves out.
MORE_DEFAULTS: dict[str, dict[str, Any]] = {
    "icon": {"icon": "heart", "at": {"anchor": "center"}, "size": "12%r"},
    "gauge": {"style": "bar", "value": "system.battery", "max": 100,
              "at": {"anchor": "center"}, "size": {"width": "40%", "height": "3%"}},
    "graph": {"at": {"anchor": "center"}, "size": {"width": "50%", "height": "20%"}},
    "pattern": {"pattern": "radial", "at": {"anchor": "center"}, "count": 12,
                "parts": [{"type": "line", "at": {"dy": "-96%r"}, "to": {"dy": "-88%r"},
                           "thickness": "2px"}]},
    "data": {"at": {"anchor": "center"}},
    "hands": {"at": {"anchor": "center"}},
    "group": {"children": {}},
}

#: Types drawn without a `color:` of their own.
_NO_COLOR = frozenset({"group", "hands"})


def element_types() -> list[str]:
    return sorted(set(DEFAULTS) | set(MORE_DEFAULTS))


def _graph_range(series: str) -> str | int:
    """A range the series can show: a week of days, half a day of hours,
    four hours of heart rate."""
    from .. import series as series_catalog

    definition = series_catalog.get(series)
    interval = getattr(definition, "interval_seconds", None)
    if interval is None:
        return "4h"
    return "7d" if interval >= 86400 else "12h" if interval >= 3600 else 12


def new_fields(index: SpanIndex, type_: str, choice: str | None = None) -> dict[str, Any]:
    """What a new element of ``type_`` starts with: its defaults, the face's
    most used colour, and the series, slot or set ``choice`` names."""
    if type_ not in DEFAULTS and type_ not in MORE_DEFAULTS:
        raise Refused(f"there is no element type {type_!r}")
    fields: dict[str, Any] = {"type": type_,
                              **copy.deepcopy(DEFAULTS.get(type_) or MORE_DEFAULTS[type_])}
    if type_ in CHOICES:
        if not choice:
            raise Refused(f"a {type_} needs its {CHOICES[type_]}")
        fields[CHOICES[type_]] = choice
        if type_ == "graph":
            fields["range"] = _graph_range(choice)
    if type_ not in _NO_COLOR:
        fields["color"] = face_color(index)
    return fields


def fresh_id(index: SpanIndex, base: str) -> str:
    taken = index.element_ids()
    n = 1
    while True:
        candidate = base if n == 1 else f"{base}{n}"
        if candidate not in taken:
            return candidate
        n += 1


# -- text helpers ---------------------------------------------------------------------

def _reindent(segment: str, old: int, new: int) -> str:
    out = []
    for line in segment.splitlines(keepends=True):
        if not line.strip():
            out.append("\n" if line.endswith("\n") else "")
        elif new >= old:
            out.append(" " * (new - old) + line)
        else:
            cut = min(old - new, len(line) - len(line.lstrip(" ")))
            out.append(line[cut:])
    return "".join(out)


def _segment(index: SpanIndex, entry: Entry) -> tuple[str, int]:
    """An element's lines, leading comments included, and its key's column."""
    start, end = index.entry_range(entry)
    return index.text[start:end], int(entry.key.start_mark.column)


def _block_entry(index: SpanIndex, block: Path) -> Entry | None:
    return index.get(tuple(block))


def _check_block(index: SpanIndex, block: Path) -> None:
    if not block or block[-1] not in ELEMENT_BLOCKS:
        raise Refused(f"{dotted(block)} is not an element block "
                      "(static:, elements: or a group's children:)")
    if block[-1] == "children":
        group = index.get(tuple(block[:-1]))
        if group is None or not is_element(index, group) or \
                _data_at(index.data, tuple(block[:-1])).get("type") != "group":
            raise Refused(f"{dotted(block[:-1])} is not a group")


def _paste(index: SpanIndex, block: Path, lines: str, column: int,
           before: str | None) -> str:
    """The text with an element's ``lines`` (written at ``column``) pasted
    into ``block``: before the element ``before``, or at its end. The block
    is created when it does not exist; an empty one (`{}`, nothing) is
    filled."""
    text = index.text
    holder = _block_entry(index, block)
    if holder is not None and isinstance(holder.value, MappingNode) and \
            not holder.value.flow_style and holder.value.value:
        mapping = holder.value
        indent = int(mapping.value[0][0].start_mark.column)
        siblings = [e for e in index.entries() if e.parent is mapping]
        if before is not None:
            anchor = next((e for e in siblings if e.name == before), None)
            if anchor is None:
                raise Refused(f"{before} is not in {dotted(block)}")
            at = index.entry_range(anchor)[0]
        else:
            at = index.value_end(siblings[-1])
        return text[:at] + _reindent(lines, column, indent) + text[at:]
    if holder is not None:
        value = holder.value
        empty = (isinstance(value, MappingNode) and not value.value) or (
            isinstance(value, ScalarNode) and value.value in ("", "~", "null"))
        if not empty:
            raise Refused(f"{dotted(block)} is not a block of elements")
        # an empty value sits on its key's line: the rest of it goes
        indent = int(holder.key.start_mark.column) + 2
        colon = text.index(":", holder.key.end_mark.index) + 1
        eol = line_end(text, holder.key.start_mark.index)
        return text[:colon] + "\n" + _reindent(lines, column, indent) + text[eol:]
    # the block itself is new: its key in its parent mapping
    parent_path = tuple(block[:-1])
    if parent_path:
        parent = index.get(parent_path)
        if parent is None or not isinstance(parent.value, MappingNode) or \
                parent.value.flow_style:
            raise Refused(f"{dotted(parent_path)} is not a block mapping")
        mapping = parent.value
        indent = (int(mapping.value[0][0].start_mark.column) if mapping.value
                  else int(parent.key.start_mark.column) + 2)
        siblings = [e for e in index.entries() if e.parent is mapping]
        at = index.value_end(siblings[-1]) if siblings else line_end(
            text, parent.key.start_mark.index)
    else:
        indent = 0
        at = len(text)
    head = " " * indent + key_text(str(block[-1])) + ":\n"
    sep = "\n" if not parent_path and text and not text.endswith("\n\n") else ""
    return text[:at] + sep + head + _reindent(lines, column, indent + 2) + text[at:]


def _put(expected: Any, block: Path, name: str, value: Any, before: str | None) -> None:
    """Into the data: ``name: value`` in ``block``, created when missing."""
    holder: Any = expected
    for step in block[:-1]:
        holder = holder[step]
    if not isinstance(holder.get(block[-1]), dict):
        holder[block[-1]] = {}
    target = holder[block[-1]]
    if before is None:
        target[name] = value
        return
    items = list(target.items())
    at = [k for k, _ in items].index(before)
    items.insert(at, (name, value))
    target.clear()
    target.update(items)


# -- the patches ------------------------------------------------------------------------

def _move_to(index: SpanIndex, path: Path, block: Path, before: str | None) -> Patch:
    path, block = tuple(path), tuple(block)
    entry = index[path]
    if not is_element(index, entry):
        raise Refused(f"{dotted(path)} is not an element")
    if entry.is_flow:
        raise Refused(f"{entry.name} is in a flow mapping; edit it in the text")
    _check_block(index, block)
    if block == path[:-1]:
        raise Refused(f"{entry.name} is already in {dotted(block)}")
    if block[:len(path)] == path:
        raise Refused(f"{entry.name} cannot move into itself")
    if before == entry.name:
        raise Refused(f"{entry.name} cannot go before itself")
    lines, column = _segment(index, entry)
    value = copy.deepcopy(_data_at(index.data, path))
    removed = _remove(index, path)
    after = index_for(removed.text)
    if _block_entry(after, block) is None and len(block) > 1 and \
            after.get(tuple(block[:-1])) is None:
        raise Refused(f"{dotted(block[:-1])} would not exist after the move")
    text = _paste(after, block, lines, column, before)
    expected = copy.deepcopy(removed.expected)
    _put(expected, block, entry.name, value, before)
    return Patch(text, expected, f"move {entry.name} to {dotted(block)}")


def _add(index: SpanIndex, type_: str, block: Path, before: str | None,
         element_id: str | None, choice: str | None) -> Patch:
    block = tuple(block)
    _check_block(index, block)
    fields = new_fields(index, type_, choice)
    new_id = element_id or fresh_id(index, f"new_{type_}")
    if new_id in index.element_ids():
        raise Refused(f"there is already an element called {new_id}")
    lines = f"{key_text(new_id)}:\n" + _block(fields, 2)
    text = _paste(index, block, lines, 0, before)
    expected = _with(index)
    _put(expected, block, new_id, fields, before)
    return Patch(text, expected, f"add {new_id}")


def _group(index: SpanIndex, paths: list[Path], group_id: str | None) -> Patch:
    paths = [tuple(p) for p in paths]
    if not paths:
        raise Refused("nothing to group")
    entries = [index[p] for p in paths]
    for e in entries:
        if not is_element(index, e):
            raise Refused(f"{dotted(e.path)} is not an element")
        if e.is_flow:
            raise Refused(f"{e.name} is in a flow mapping; edit it in the text")
    block = paths[0][:-1]
    if any(p[:-1] != block for p in paths):
        raise Refused("only elements side by side in one block can be grouped")
    entries.sort(key=lambda e: e.key.start_mark.index)
    new_id = group_id or fresh_id(index, "group")
    if new_id in index.element_ids():
        raise Refused(f"there is already an element called {new_id}")
    column = int(entries[0].key.start_mark.column)
    text = index.text
    siblings = [e for e in index.entries() if e.parent is entries[0].parent]
    at = siblings.index(entries[0])
    first_start = index.entry_range(entries[0])[0]
    if [e.name for e in siblings[at:at + len(entries)]] == [e.name for e in entries]:
        # side by side: their whole span, the blank lines between them kept
        # inside the group, so ungrouping gives the text back as it was
        last_end = index.value_end(entries[-1])
        children = _reindent(text[first_start:last_end], column, column + 4)
        text = text[:first_start] + text[last_end:]
    else:
        children = "".join(_reindent(_segment(index, e)[0], column, column + 4)
                           for e in entries)
        for e in reversed(entries):
            start, end = index.entry_range(e)
            text = text[:start] + text[end:]
    group_lines = (" " * column + f"{key_text(new_id)}:\n" + " " * (column + 2)
                   + "type: group\n" + " " * (column + 2) + "children:\n" + children)
    text = text[:first_start] + group_lines + text[first_start:]
    expected = _with(index)
    holder = _data_at(expected, block)
    members = {e.name: holder[e.name] for e in entries}
    items: list[tuple[Any, Any]] = []
    for k, v in holder.items():
        if k == entries[0].name:
            items.append((new_id, {"type": "group", "children": members}))
        elif k not in members:
            items.append((k, v))
    holder.clear()
    holder.update(items)
    return Patch(text, expected, f"group {', '.join(e.name for e in entries)} as {new_id}")


def _ungroup(index: SpanIndex, path: Path) -> Patch:
    path = tuple(path)
    entry = index[path]
    data = _data_at(index.data, path)
    if not is_element(index, entry) or data.get("type") != "group":
        raise Refused(f"{dotted(path)} is not a group")
    if entry.is_flow:
        raise Refused(f"{entry.name} is in a flow mapping; edit it in the text")
    extra = [k for k in data if k not in ("type", "children")]
    if extra:
        raise Refused(f"{entry.name} has {', '.join(extra)}, which its children take from "
                      "it; remove those first, or edit it in the text")
    children = index.get(path + ("children",))
    column = int(entry.key.start_mark.column)
    lifted = ""
    if children is not None and isinstance(children.value, MappingNode) and \
            children.value.value:
        if children.value.flow_style:
            raise Refused(f"{entry.name}'s children are in a flow mapping; edit them in the text")
        inner = int(children.value.value[0][0].start_mark.column)
        first = next(e for e in index.entries() if e.parent is children.value)
        start = index.entry_range(first)[0]
        end = index.value_end(children)
        lifted = _reindent(index.text[start:end], inner, column)
    g0, g1 = index.entry_range(entry)
    text = index.text[:g0] + lifted + index.text[g1:]
    expected = _with(index)
    holder = _data_at(expected, path[:-1])
    kids = data.get("children") or {}
    clash = [k for k in kids if k in holder and k != entry.name]
    if clash:
        raise Refused(f"{', '.join(clash)} already exist beside {entry.name}")
    items: list[tuple[Any, Any]] = []
    for k, v in holder.items():
        if k == entry.name:
            items.extend((ck, copy.deepcopy(cv)) for ck, cv in kids.items())
        else:
            items.append((k, v))
    holder.clear()
    holder.update(items)
    return Patch(text, expected, f"ungroup {entry.name}")


# -- the public operations ---------------------------------------------------------------

def move_to_block(index: SpanIndex, path: Path, block: Path,
                  before: str | None = None) -> Patch:
    """Move the element at ``path`` into ``block`` (another block's path:
    `("static",)`, `("layouts", "big", "elements")`, a group's
    `(..., "children")`), before its element ``before`` or at its end."""
    return _ended_patch(index, _move_to, path, block, before)


def add(index: SpanIndex, type_: str, block: Path = ("elements",), before: str | None = None,
        element_id: str | None = None, choice: str | None = None) -> Patch:
    """Add a new element of any type to ``block``, before ``before`` or at
    its end (`new_fields`)."""
    return _ended_patch(index, _add, type_, block, before, element_id, choice)


def group(index: SpanIndex, paths: list[Path], group_id: str | None = None) -> Patch:
    """Wrap sibling elements in a new group, where the first of them was."""
    return _ended_patch(index, _group, paths, group_id)


def ungroup(index: SpanIndex, path: Path) -> Patch:
    """Put a group's children where it was, and remove it."""
    return _ended_patch(index, _ungroup, path)
