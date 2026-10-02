"""Text patches: every edit the editor makes, as characters rewritten in
the design's own text.

Each function takes a `SpanIndex` and returns a `Patch`: the new text and
the plain data it must parse to. The data is computed from the original
data with the one intended change, never from the new text, so the gate
(`wfb.edit.gate`) can check the text against it. A patch never
re-serialises anything it does not change, so comments, quoting, flow or
block style and blank lines outside the edit stay byte for byte.

Three rules, each found on the example corpus:

- a block value ends where the next token starts (`SpanIndex.value_end`);
- removing the last entry of a block mapping removes the mapping's own key
  too, since an emptied block mapping parses as null;
- a duplicate renames every element id inside it, the element's own and
  each descendant's, or a copied group's children clash with the original's.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

from ruamel.yaml.nodes import MappingNode, Node, ScalarNode

from .spans import (
    Entry, Path, Refused, SpanIndex, dotted, is_element, line_start, parse,
)


@dataclass(frozen=True)
class Patch:
    """A patched text and the data it must parse to."""

    text: str
    expected: Any
    #: What the patch does, in the author's terms: "set elements.clock.at.dy".
    what: str


# -- rendering values -----------------------------------------------------------

_PLAIN_SAFE = re.compile(r"^[A-Za-z0-9_.%#+\-/][A-Za-z0-9_.%#+\-/ ]*$")


def number(value: float) -> str:
    """A number as the shortest plain text that reads back as it: no
    exponent, no trailing zeros."""
    if float(value).is_integer():
        return str(int(value))
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def scalar(value: Any, style: str | None = None) -> str:
    """``value`` as a YAML scalar, in ``style`` (a node's own: `'"'`,
    `"'"` or `None` for plain) when that still reads back as ``value``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return number(value)
    text = str(value)
    if style == "'":
        return "'" + text.replace("'", "''") + "'"
    if style == '"':
        return json.dumps(text, ensure_ascii=False)
    if _PLAIN_SAFE.match(text) and not text.endswith(" ") and _reads_back(text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _reads_back(text: str) -> bool:
    try:
        return bool(parse(f"k: {text}\n") == {"k": text})
    except Refused:
        return False


def key_text(key: str) -> str:
    """A mapping key: plain, unless it would not read back or holds a
    colon (`"shape:round"`, the guide's own spelling)."""
    if ":" in key or not _PLAIN_SAFE.match(key) or not _reads_back(key):
        return json.dumps(key, ensure_ascii=False)
    return key


def flow(value: Any) -> str:
    """``value`` in flow style, the examples' spacing: `{ a: 1, b: 2 }`."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{key_text(str(k))}: {flow(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(flow(v) for v in value) + "]"
    return scalar(value)


# -- data helpers ---------------------------------------------------------------

def _data_at(data: Any, path: Path) -> Any:
    for step in path:
        data = data[step]
    return data


def _with(index: SpanIndex) -> Any:
    return copy.deepcopy(index.data)


def _nested(rest: Path, value: Any) -> Any:
    for step in reversed(rest):
        value = {step: value}
    return value


def _insert_after(mapping: dict[Any, Any], after: Any, key: Any, value: Any) -> None:
    items = list(mapping.items())
    at = [k for k, _ in items].index(after) + 1 if after is not None else len(items)
    items.insert(at, (key, value))
    mapping.clear()
    mapping.update(items)


# -- text helpers -----------------------------------------------------------------

def _ended(index: SpanIndex) -> tuple[SpanIndex, bool]:
    """``index``, re-indexed with a final newline when the text has none,
    so every line-range rule holds at the end of the file too; and whether
    one was added (`_restore` takes it off again)."""
    if index.text and not index.text.endswith("\n"):
        return SpanIndex(index.text + "\n"), True
    return index, False


def _restore(text: str, added: bool) -> str:
    return text[:-1] if added and text.endswith("\n") else text


def _block_indent(index: SpanIndex, mapping: MappingNode) -> int:
    return int(mapping.value[0][0].start_mark.column) if mapping.value else 0


def _last_entry(index: SpanIndex, mapping: MappingNode) -> Entry:
    key, _ = mapping.value[-1]
    for entry in index.entries():
        if entry.parent is mapping and entry.key is key:
            return entry
    raise Refused("the mapping's last entry is not in the index")


def _mapping_at(index: SpanIndex, path: Path) -> MappingNode:
    if not path:
        if not isinstance(index.root, MappingNode):
            raise Refused("the file is not a mapping")
        return index.root
    entry = index[path]
    if not isinstance(entry.value, MappingNode):
        raise Refused(f"{dotted(path)} is not a mapping")
    return entry.value


def _insert_key(index: SpanIndex, mapping: MappingNode, key: str, value: Any,
                after: Entry | None = None) -> str:
    """The text with ``key: value`` added to ``mapping``: before a flow
    mapping's closing brace, or on its own line at a block mapping's indent
    after its last entry (or after ``after``)."""
    text = index.text
    if mapping.flow_style:
        close = mapping.end_mark.index - 1
        if text[close] != "}":
            raise Refused("cannot find the flow mapping's closing brace")
        before = text[:close].rstrip()
        sep = "" if before.endswith("{") else ","
        pad = " " if text[close - 1] == " " or before.endswith("{") else ""
        return (before + f"{sep} {key_text(key)}: {flow(value)}" + pad + text[close:])
    if not mapping.value:
        raise Refused("cannot add a key to an empty mapping")
    indent = _block_indent(index, mapping)
    end = index.value_end(after or _last_entry(index, mapping))
    line = " " * indent + f"{key_text(key)}: {flow(value)}\n"
    return (text[:end] + line + text[end:])


# -- scalar and key patches ------------------------------------------------------

def _set_value(index: SpanIndex, path: Path, value: Any) -> Patch:
    path = tuple(path)
    expected = _with(index)
    entry = index.get(path)
    if entry is not None:
        parent_data = _data_at(expected, path[:-1])
        parent_data[path[-1]] = value
        node = entry.value
        if isinstance(node, ScalarNode) and not isinstance(value, (dict, list)):
            new = scalar(value, node.style if node.style in ("'", '"') else None)
        elif getattr(node, "flow_style", False) or isinstance(node, ScalarNode):
            new = flow(value)
        else:
            raise Refused(f"{dotted(path)} is a block; edit its keys one by one")
        start, end = node.start_mark.index, node.end_mark.index
        if isinstance(node, ScalarNode) and node.value == "" and node.style is None:
            # an empty value (`key:`) has a zero-width node: write after the colon
            start = end = index.text.index(":", entry.key.end_mark.index) + 1
            new = " " + new
        text = index.text[:start] + new + index.text[end:]
        return Patch(text, expected, f"set {dotted(path)}")
    # the deepest existing ancestor that is a mapping
    for depth in range(len(path) - 1, -1, -1):
        prefix = path[:depth]
        if depth == 0 or index.get(prefix) is not None:
            break
    mapping = _mapping_at(index, prefix)
    rest = path[depth:]
    if any(not isinstance(step, str) for step in rest):
        raise Refused(f"cannot create the list item {dotted(path)}")
    holder = _data_at(expected, prefix)
    if not isinstance(holder, dict):
        raise Refused(f"{dotted(prefix)} is not a mapping")
    holder[rest[0]] = _nested(rest[1:], value)
    text = _insert_key(index, mapping, str(rest[0]), _nested(rest[1:], value))
    return Patch(text, expected, f"set {dotted(path)}")


def _remove(index: SpanIndex, path: Path) -> Patch:
    entry = index[tuple(path)]
    expected = _with(index)
    holder = index.holder(entry.parent)
    if not entry.is_flow and len(entry.parent.value) == 1 and holder is not None:
        removed = _remove(index, holder.path)
        return Patch(removed.text, removed.expected, f"remove {dotted(entry.path)}")
    del _data_at(expected, entry.path[:-1])[entry.path[-1]]
    text = index.text
    if entry.is_flow:
        pairs = entry.parent.value
        i = next(i for i, (k, _) in enumerate(pairs) if k is entry.key)
        if len(pairs) == 1:
            start, end = entry.parent.start_mark.index, entry.parent.end_mark.index
            return Patch((text[:start] + "{}" + text[end:]), expected,
                         f"remove {dotted(entry.path)}")
        start, end = entry.key.start_mark.index, entry.value.end_mark.index
        if i + 1 < len(pairs):
            end = pairs[i + 1][0].start_mark.index      # eat the following ", "
        else:
            start = pairs[i - 1][1].end_mark.index      # eat the preceding ", "
        return Patch((text[:start] + text[end:]), expected, f"remove {dotted(entry.path)}")
    start, end = index.entry_range(entry)
    return Patch((text[:start] + text[end:]), expected, f"remove {dotted(entry.path)}")


# -- element patches -------------------------------------------------------------

def _element(index: SpanIndex, path: Path) -> Entry:
    entry = index[tuple(path)]
    if not is_element(index, entry):
        raise Refused(f"{dotted(path)} is not an element")
    if entry.is_flow:
        raise Refused(f"{entry.name} is in a flow mapping; edit it in the text")
    return entry


def _delete_element(index: SpanIndex, path: Path) -> Patch:
    entry = _element(index, path)
    patch = _remove(index, entry.path)
    return Patch(patch.text, patch.expected, f"delete {entry.name}")


def fresh_suffix(index: SpanIndex, ids: list[str], base: str = "_copy") -> str:
    """The first of `_copy`, `_copy2`, ... that gives every id in ``ids``
    a name no element in the file has."""
    taken = index.element_ids()
    n = 1
    while True:
        suffix = base if n == 1 else f"{base}{n}"
        if not any(i + suffix in taken for i in ids):
            return suffix
        n += 1


def _duplicate_element(index: SpanIndex, path: Path) -> Patch:
    entry = _element(index, path)
    text = index.text
    start, end = index.entry_range(entry)
    inside = [e for e in index.elements() if start <= e.key.start_mark.index < end]
    suffix = fresh_suffix(index, [e.name for e in inside])
    block = text[start:end]
    for e in sorted(inside, key=lambda e: e.key.start_mark.index, reverse=True):
        at = e.key.start_mark.index - start
        width = e.key.end_mark.index - e.key.start_mark.index
        block = block[:at] + key_text(e.name + suffix) + block[at + width:]
    block = block[line_start(block, entry.key.start_mark.index - start):]
    expected = _with(index)
    parent = _data_at(expected, entry.path[:-1])
    renamed = {e.path[len(entry.path):] for e in inside}
    copy_ = _renamed(copy.deepcopy(parent[entry.name]), renamed, suffix, ())
    _insert_after(parent, entry.name, entry.name + suffix, copy_)
    return Patch((text[:end] + block + text[end:]), expected,
                 f"duplicate {entry.name} as {entry.name + suffix}")


def _renamed(node: Any, paths: set[Path], suffix: str, here: Path) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            inner = here + (k,)
            out[k + suffix if inner in paths else k] = _renamed(v, paths, suffix, inner)
        return out
    if isinstance(node, list):
        return [_renamed(v, paths, suffix, here + (i,)) for i, v in enumerate(node)]
    return node


def _move_element(index: SpanIndex, path: Path, to: int) -> Patch:
    entry = _element(index, path)
    siblings = [e for e in index.entries() if e.parent is entry.parent]
    here = siblings.index(entry)
    if not 0 <= to < len(siblings):
        raise Refused(f"{entry.name} cannot move to position {to} of {len(siblings)}")
    expected = _with(index)
    parent = _data_at(expected, entry.path[:-1])
    items = list(parent.items())
    item = items.pop(here)
    items.insert(to, item)
    parent.clear()
    parent.update(items)
    if to == here:
        return Patch(index.text, expected, f"move {entry.name}")
    text = index.text
    b0, b1 = index.entry_range(entry)
    segment = text[b0:b1]
    if to < here:
        a0, _ = index.entry_range(siblings[to])
        new = text[:a0] + segment + text[a0:b0] + text[b1:]
    else:
        a1 = index.value_end(siblings[to])
        new = text[:b0] + text[b1:a1] + segment + text[a1:]
    return Patch((new), expected, f"move {entry.name} to position {to}")


#: What a new element of each type starts with, besides its colour.
DEFAULTS: dict[str, dict[str, Any]] = {
    "rectangle": {"at": {"anchor": "center"}, "size": {"width": "20%", "height": "10%"}},
    "ellipse": {"at": {"anchor": "center"}, "size": {"width": "20%", "height": "10%"}},
    "circle": {"at": {"anchor": "center"}, "radius": "10%r"},
    "arc": {"at": {"anchor": "center"}, "radius": "80%r", "thickness": "3px",
            "start_angle": "0deg", "sweep": "90deg"},
    "line": {"at": {"anchor": "center"}, "to": {"anchor": "center", "dx": "20%r"},
             "thickness": "2px"},
    "polygon": {"points": [{"anchor": "center", "dy": "-10%r"},
                           {"anchor": "center", "dx": "-9%r", "dy": "5%r"},
                           {"anchor": "center", "dx": "9%r", "dy": "5%r"}]},
    "text": {"text": "Text", "font": "FONT_SMALL", "at": {"anchor": "center"}},
}


def face_color(index: SpanIndex) -> str:
    """A colour the face already uses: the palette colour most element
    `color:` keys name (the first, on a tie), else the palette's first
    colour, else white. The most used, not the first, because the first is
    usually the background's."""
    counts: dict[str, int] = {}
    for entry in index.entries():
        if (entry.name == "color" and isinstance(entry.value, ScalarNode)
                and str(entry.value.value).startswith("color.")):
            name = str(entry.value.value)
            counts[name] = counts.get(name, 0) + 1
    if counts:
        return max(counts, key=lambda name: counts[name])
    palette = index.data.get("resources", {}).get("palette") if isinstance(index.data, dict) else None
    if isinstance(palette, dict) and palette:
        return f"color.{next(iter(palette))}"
    return "#FFFFFF"


def _add_element(index: SpanIndex, type_: str, *, block: Path = ("elements",),
                after: str | None = None, element_id: str | None = None) -> Patch:
    """Add a new element of ``type_`` to ``block`` (the top level's
    `elements:` by default), after the element ``after`` or at the end,
    with `DEFAULTS` and `face_color`."""
    if type_ not in DEFAULTS:
        raise Refused(f"adding a {type_} is not supported yet; write it in the text")
    fields: dict[str, Any] = {"type": type_, **copy.deepcopy(DEFAULTS[type_]),
                              "color": face_color(index)}
    taken = index.element_ids()
    new_id = element_id or next(f"new_{type_}" + ("" if n == 1 else str(n))
                                for n in range(1, 10_000)
                                if f"new_{type_}" + ("" if n == 1 else str(n)) not in taken)
    if new_id in taken:
        raise Refused(f"there is already an element called {new_id}")
    expected = _with(index)
    text = index.text
    holder = index.get(tuple(block))
    if holder is None:
        if len(block) != 1:
            raise Refused(f"{dotted(block)} does not exist")
        expected[block[0]] = {new_id: fields}
        lines = [f"{key_text(str(block[0]))}:", f"  {key_text(new_id)}:"]
        lines += [f"    {key_text(k)}: {flow(v)}" for k, v in fields.items()]
        sep = "" if text == "" or text.endswith("\n\n") else "\n"
        return Patch((text + sep + "\n".join(lines) + "\n"), expected, f"add {new_id}")
    mapping = holder.value
    if not isinstance(mapping, MappingNode) or mapping.flow_style or not mapping.value:
        raise Refused(f"{dotted(block)} is not a block of elements")
    indent = _block_indent(index, mapping)
    anchor = index[tuple(block) + (after,)] if after is not None else _last_entry(index, mapping)
    end = index.value_end(anchor)
    lines = [" " * indent + f"{key_text(new_id)}:"]
    lines += [" " * (indent + 2) + f"{key_text(k)}: {flow(v)}" for k, v in fields.items()]
    _insert_after(_data_at(expected, tuple(block)), after, new_id, fields)
    return Patch((text[:end] + "\n".join(lines) + "\n" + text[end:]), expected,
                 f"add {new_id}")


# -- the public operations: each runs on text with a final newline -------------

def _ended_patch(index: SpanIndex, op: Any, *args: Any, **kw: Any) -> Patch:
    ended, added = _ended(index)
    patch: Patch = op(ended, *args, **kw)
    return Patch(_restore(patch.text, added), patch.expected, patch.what)


def set_value(index: SpanIndex, path: Path, value: Any) -> Patch:
    """Set the value at ``path``: rewrite an existing scalar in place in its
    own quoting, replace a flow value, or add the missing keys, as a nested
    flow value under the deepest mapping that exists."""
    return _ended_patch(index, _set_value, path, value)


def remove(index: SpanIndex, path: Path) -> Patch:
    """Remove the key at ``path``. The last entry of a block mapping takes
    its mapping's key with it."""
    return _ended_patch(index, _remove, path)


def delete_element(index: SpanIndex, path: Path) -> Patch:
    """Delete an element with its leading comment lines. A block's only
    element takes the block's key with it (`static:` with nothing under it
    would parse as null)."""
    return _ended_patch(index, _delete_element, path)


def duplicate_element(index: SpanIndex, path: Path) -> Patch:
    """Copy an element right after itself, every element id inside the copy
    renamed with one fresh suffix. Leading comments are not copied."""
    return _ended_patch(index, _duplicate_element, path)


def move_element(index: SpanIndex, path: Path, to: int) -> Patch:
    """Move an element to position ``to`` among its siblings (0 is first),
    its leading comments with it."""
    return _ended_patch(index, _move_element, path, to)


def add_element(index: SpanIndex, type_: str, *, block: Path = ("elements",),
                after: str | None = None, element_id: str | None = None) -> Patch:
    """Add a new element of ``type_`` to ``block`` (the top level's
    `elements:` by default), after the element ``after`` or at the end,
    with `DEFAULTS` and `face_color`."""
    return _ended_patch(index, _add_element, type_, block=block, after=after,
                        element_id=element_id)


def node_text(index: SpanIndex, node: Node) -> str:
    return index.text[node.start_mark.index:node.end_mark.index]
