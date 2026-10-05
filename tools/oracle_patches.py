"""The `patches` stage of tools/oracle.py: a fixed battery of editor
operations run on one design's text, each recorded with its arguments and
its outcome, so the TypeScript patch engine can replay the same calls.

Every operation of `wfb.edit`'s patch, structure, colour, scheme and hand-set
modules is called with arguments derived from the design itself:
- set, insert, remove and rename on every entry;
- delete, duplicate, move, regroup and recolour on every element;
- adding every element type;
- every palette swatch renamed and recoloured;
- every slot, scheme, role and hand set edited.

An outcome is one of:
- `{"splice": [at, cut, insert], "what": ..., "expected": ...}`: the patched
  text as one splice of the original (code-point offsets);
- `{"refused": message}`;
- `{"crash": exception type}` for anything else raised.

`expected` is the sha256 of the patch's intended data in `canonical`
form, which TypeScript reproduces exactly: parsing each patched text to
check it instead would cost 50 times the patch itself.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
from typing import Any, Callable

from wfb.edit import colors, hands, schemes, structure
from wfb.edit import patch as patches
from wfb.edit.spans import Refused, SpanIndex

Record = dict[str, Any]


def _splice(before: str, after: str) -> list[Any]:
    """`after` as one cut of `before`: where, how many characters cut, what inserted."""
    start = 0
    limit = min(len(before), len(after))
    while start < limit and before[start] == after[start]:
        start += 1
    end_b, end_a = len(before), len(after)
    while end_b > start and end_a > start and before[end_b - 1] == after[end_a - 1]:
        end_b -= 1
        end_a -= 1
    return [start, end_b - start, after[start:end_a]]


def canonical(data: Any) -> str:
    """`data` as one string both languages write the same: a number that is
    an integer as an integer (`1` and `1.0` are one value, as in Python's
    `==`), any other as `float.hex()`; a string as `ensure_ascii` JSON; a
    mapping as its `[key, value]` pairs in order."""
    if data is None:
        return "n"
    if isinstance(data, bool):
        return "t" if data else "f"
    if isinstance(data, int):
        return f"i{data}"
    if isinstance(data, float):
        if math.isfinite(data) and data.is_integer() and abs(data) < 2 ** 53:
            return f"i{int(data)}"
        return f"x{data.hex()}"
    if isinstance(data, str):
        return json.dumps(data, ensure_ascii=True)
    if isinstance(data, (datetime.date, datetime.datetime)):
        return f"T{data.isoformat()}"
    if isinstance(data, dict):
        return "{" + ",".join(f"{canonical(k)}:{canonical(v)}" for k, v in data.items()) + "}"
    if isinstance(data, (list, tuple)):
        return "[" + ",".join(canonical(v) for v in data) + "]"
    raise TypeError(f"canonical: no form for {type(data).__name__}")


def digest(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode("ascii")).hexdigest()


def _mutated(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.5
    if isinstance(value, str):
        return value + "x"
    if value is None:
        return 1
    if isinstance(value, list):
        return []
    return {"zz": 1}


def _data_at(data: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        data = data[step]
    return data


class Battery:
    def __init__(self, index: SpanIndex, to_json: Callable[..., Any]) -> None:
        #: Shared by every call: an index is read-only, and building one is
        #: most of an operation's cost.
        self.index = index
        self.text = index.text
        self.to_json = to_json
        self.records: list[Record] = []

    def run(self, op: str, fn: Callable[..., Any], *args: Any, **kw: Any) -> None:
        index = self.index
        record: Record = {"op": op, "args": [self.to_json(list(a) if isinstance(a, tuple) else a,
                                                          top=False) for a in args],
                          "kw": {k: self.to_json(v, top=False) for k, v in kw.items()}}
        try:
            out = fn(index, *args, **kw)
        except Refused as exc:
            record["refused"] = str(exc)
        except Exception as exc:  # recorded, not raised: the port must crash too
            record["crash"] = type(exc).__name__
        else:
            name = None
            if isinstance(out, tuple):  # add_swatch: (patch, name)
                out, name = out
            if isinstance(out, patches.Patch):
                record["splice"] = _splice(self.text, out.text)
                record["what"] = out.what
                record["expected"] = digest(out.expected)
                if name is not None:
                    record["name"] = name
            else:
                record["value"] = self.to_json(out, top=False)
        self.records.append(record)


def battery(text: str, to_json: Callable[..., Any]) -> list[Record]:
    """Every operation's record for `text`, in a fixed order."""
    try:
        index = SpanIndex(text)
    except Refused:
        return []
    if not isinstance(index.data, dict):
        return []
    b = Battery(index, to_json)
    data = index.data

    # -- entries ------------------------------------------------------------
    for e in index.entries():
        value = _data_at(data, e.path)
        b.run("set_value", patches.set_value, e.path, _mutated(value))
        if isinstance(value, dict):
            b.run("set_value", patches.set_value, e.path + ("zz_new",), 7)
            b.run("set_value", patches.set_value, e.path + ("zz_new", "inner"), "v", block=True)
        b.run("remove", patches.remove, e.path)
        b.run("rename_key", patches.rename_key, e.path, f"{e.name}_r")

    # -- elements -----------------------------------------------------------
    elements = index.elements()
    blocks = list(dict.fromkeys(e.path[:-1] for e in elements))
    for e in elements:
        siblings = [s for s in index.entries() if s.parent is e.parent]
        b.run("delete_element", patches.delete_element, e.path)
        b.run("duplicate_element", patches.duplicate_element, e.path)
        b.run("move_element", patches.move_element, e.path, 0)
        b.run("move_element", patches.move_element, e.path, len(siblings) - 1)
        b.run("ungroup", structure.ungroup, e.path)
        for block in (("static",), ("elements",)):
            b.run("move_to_block", structure.move_to_block, e.path, block)
        b.run("group", structure.group, [e.path])
        at = siblings.index(e)
        if at + 1 < len(siblings):
            b.run("group", structure.group, [e.path, siblings[at + 1].path], group_id="zz_group")
        for color in ("#FF8000", "#55AAFF"):
            b.run("use_color", colors.use_color, e.path + ("color",), color)
    if len(elements) >= 2:
        b.run("delete_elements", patches.delete_elements, [elements[0].path, elements[1].path])
    if elements:
        first = elements[0]
        scalars = [(s.path, _mutated(_data_at(data, s.path))) for s in index.entries()
                   if s.path[:len(first.path)] == first.path and len(s.path) == len(first.path) + 1
                   and s.value.__class__.__name__ == "ScalarNode"]
        b.run("set_scalars", patches.set_scalars, scalars)
        start, end = index.entry_range(first)
        b.run("paste", structure.paste, text[start:end])
        b.run("paste", structure.paste, text[start:end], ("static",))

    slots = list(((data.get("config") or {}).get("slots") or {}))
    sets = list(((data.get("resources") or {}).get("hand_sets") or {}))
    choices = {"data": slots[0] if slots else None, "hands": sets[0] if sets else None,
                "graph": "heart_rate"}
    for type_ in sorted(patches.DEFAULTS):
        b.run("add_element", patches.add_element, type_)
    for block in [("elements",), ("static",), *blocks[:3]]:
        for type_ in structure.element_types():
            b.run("add", structure.add, type_, block, choice=choices.get(type_))
    b.run("face_color", patches.face_color)

    # -- colours ------------------------------------------------------------
    palette = list(((data.get("resources") or {}).get("palette") or {}))
    for name in palette:
        b.run("rename_reference", patches.rename_reference,
              ("resources", "palette", name), f"{name}_r", "color.")
        for value in ("#FF0000", "#123456"):
            b.run("set_swatch", colors.set_swatch, name, value)
        b.run("user_names", colors.user_names, name)
    for value in ("#FF8000", "#FFFFFF", "#55AAFF"):
        b.run("add_swatch", colors.add_swatch, value)
    b.run("remove_unused", colors.remove_unused)
    b.run("swatches", colors.swatches)
    b.run("roles", colors.roles)
    b.run("rewrite_scalars", lambda i: patches.rewrite_scalars(
        i, lambda s: s.replace("color.", "colour."), "respell"))

    # -- slots ----------------------------------------------------------------
    for name in slots:
        b.run("rename_slot", patches.rename_slot, name, f"{name}_r")
        b.run("remove_slot", patches.remove_slot, name)

    # -- schemes and roles ------------------------------------------------------
    scheme_names = list(((data.get("theme") or {}).get("schemes") or {}))
    if scheme_names:
        b.run("add_scheme", schemes.add_scheme, "zz")
        for name in scheme_names:
            b.run("rename_scheme", schemes.rename_scheme, name, "zz")
            b.run("delete_scheme", schemes.delete_scheme, name)
            b.run("remove_theme", schemes.remove_theme, name)
        b.run("add_role", schemes.add_role, "zz", "#FF0000")
        for role in colors.roles(index):
            b.run("rename_role", schemes.rename_role, role, "zz")
            b.run("delete_role", schemes.delete_role, role)
    else:
        b.run("make_switchable", schemes.make_switchable, palette[:2], "day")

    # -- hand sets ------------------------------------------------------------
    for preset in hands.presets():
        b.run("add_hand_set", hands.add_hand_set, "zz", preset)
    for name in sets:
        b.run("duplicate_hand_set", hands.duplicate_hand_set, name)
        b.run("rename_hand_set", hands.rename_hand_set, name, "zz")
        b.run("delete_hand_set", hands.delete_hand_set, name)
    b.run("hand_summary", hands.summary)
    return b.records
