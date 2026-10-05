"""The `load-cases` stage of tools/oracle.py: seeded broken variants of a
design, each loaded pass by pass, so the TypeScript port's diagnostics are
held to Python's on input that fails, not only on faces that load clean.

A variant is the design's text with one edit made by `wfb.edit`, so comments
and layout survive:
- a value set to a wrong one from a fixed pool;
- a key removed, renamed, or added unknown;
- an element duplicated.

The edit is stored as a splice of the original text (code-point offsets),
which TypeScript applies directly. The original text is case 0.

Each case records the diagnostics after each pass of `wfb.build.load`:
`yaml`, `validate`, `lower`, `desugar` and `ir`, each as the list that pass
added, `{"crash": type}` for a pass that raised, and `null` for a pass not
reached.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Callable

from oracle_patches import _splice
from wfb import desugar, lower, validate, yamlsrc
from wfb.diagnostics import Bag
from wfb.edit import patch as patches
from wfb.edit.spans import Refused, SpanIndex
from wfb.ir import build as build_ir

#: Wrong values a variant may set: wrong types, units, references and templates.
POOL: list[Any] = [
    7, 2.0, -1, "seven", True, None, [], {}, ["x"], {"zz": 1}, "12%r", "1.5pt", "-5%", "45deg",
    "color.nope", "color.bg", "#12345", "#FFF", "{time.hour:02d", "{a ? b : c}", "{time.hour:02d} {x}",
    "FONT_NOPE", "font.nope", "top_middle", "NE", "line\nbreak", "{}", "{:%H}", "system.nope",
    "complication.steps", "4h", "0x1F",
]
CASES = 40


def _pass(bag: Bag, start: int, to_json: Callable[..., Any]) -> list[Any]:
    return [to_json(d) for d in bag.items[start:]]


def load_passes(path: Path, text: str, to_json: Callable[..., Any]) -> dict[str, Any]:
    """`wfb.build.load`, unrolled: the diagnostics each pass added, or
    `{"crash": type}` for a pass that raised (the port must fail the same
    way)."""
    out: dict[str, Any] = {"yaml": None, "validate": None, "lower": None, "desugar": None, "ir": None}
    bag = Bag()
    doc = yamlsrc.load(path, bag, text)
    out["yaml"] = _pass(bag, 0, to_json)
    if doc is None:
        return out
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("validate", lambda: validate.validate(doc, bag)),
        ("lower", lambda: lower.lower(doc, bag)),
        ("desugar", lambda: desugar.desugar(doc, bag)),
        ("ir", lambda: build_ir(doc, bag) is not None),
    ]
    for name, step in steps:
        start = len(bag.items)
        try:
            ok = step()
        except Exception as exc:
            out[name] = {"crash": type(exc).__name__}
            return out
        out[name] = _pass(bag, start, to_json)
        if not ok:
            return out
    return out


def cases(path: Path, text: str, seed: str, to_json: Callable[..., Any]) -> list[dict[str, Any]]:
    out = [{"splice": None, "what": "the design as written", **load_passes(path, text, to_json)}]
    try:
        index = SpanIndex(text)
    except Refused:
        return out
    entries = index.entries()
    if not entries:
        return out
    rng = random.Random(seed)
    made = 0
    attempts = 0
    while made < CASES and attempts < CASES * 5:
        attempts += 1
        entry = rng.choice(entries)
        kind = rng.choice(["set", "set", "set", "remove", "rename", "unknown", "duplicate"])
        try:
            if kind == "set":
                value = rng.choice(POOL)
                result = patches.set_value(index, entry.path, value)
                what = f"set {'.'.join(map(str, entry.path))} to {value!r}"
            elif kind == "remove":
                result = patches.remove(index, entry.path)
                what = f"remove {'.'.join(map(str, entry.path))}"
            elif kind == "rename":
                result = patches.rename_key(index, entry.path, f"{entry.name}x")
                what = f"rename {'.'.join(map(str, entry.path))}"
            elif kind == "unknown":
                if entry.value.__class__.__name__ != "MappingNode":
                    continue
                result = patches.set_value(index, entry.path + ("bogus_key",), 1)
                what = f"add an unknown key to {'.'.join(map(str, entry.path))}"
            else:
                elements = index.elements()
                if not elements:
                    continue
                element = rng.choice(elements)
                result = patches.duplicate_element(index, element.path)
                what = f"duplicate {element.name}"
        except Refused:
            continue
        made += 1
        out.append({"splice": _splice(text, result.text), "what": what,
                    **load_passes(path, result.text, to_json)})
    return out
