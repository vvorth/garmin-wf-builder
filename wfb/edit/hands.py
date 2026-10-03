"""Hand-set edits: `resources: hand_sets:` entries added from a preset,
duplicated, renamed with every element's `set:` following, and deleted
while nothing places them.

The presets are `wfb/templates/hands/sets.yaml`. Their `color.fg` and
`color.accent` stand for the face's main colour and its accent, and are
rewritten to colours the face has (`_face_colors`), so an added set loads.
"""

from __future__ import annotations

import copy
import functools
import re
from pathlib import Path as FilePath
from typing import Any

from .colors import roles, swatches
from .patch import Patch, _repoint, _ended_patch, chain, remove, rename_key, set_value
from .spans import Path, Refused, SpanIndex, parse
from .structure import add

PRESETS = FilePath(__file__).resolve().parents[1] / "templates" / "hands" / "sets.yaml"

#: A hand set's hands, in the order they are drawn.
HANDS = ("hour", "minute", "second")


@functools.cache
def presets() -> dict[str, Any]:
    """Every preset by name, as written in the presets file."""
    data: dict[str, Any] = parse(PRESETS.read_text(encoding="utf-8"))
    return data


def _sets(index: SpanIndex) -> dict[str, Any]:
    data = index.data if isinstance(index.data, dict) else {}
    sets = (data.get("resources") or {}).get("hand_sets") or {}
    return sets if isinstance(sets, dict) else {}


def placed_by(index: SpanIndex, name: str) -> list[str]:
    """The ids of the `hands` elements placing the set ``name``."""
    out = []
    for entry in index.elements():
        data: Any = index.data
        for step in entry.path:
            data = data[step]
        if isinstance(data, dict) and data.get("type") == "hands" and data.get("set") == name:
            out.append(entry.name)
    return out


def _face_colors(index: SpanIndex) -> dict[str, str]:
    """What a preset's `color.fg` and `color.accent` become on this face:
    a colour of that name if it has one, else its likeliest main colour
    (`text`, then `white`, then its first colour that is not `bg`)."""
    names = list(swatches(index)) + roles(index)
    main = next((n for n in ("fg", "text", "white") if n in names),
                next((n for n in names if n != "bg"), None))
    main_ref = f"color.{main}" if main else "#FFFFFF"
    accent_ref = "color.accent" if "accent" in names else main_ref
    return {"color.fg": main_ref, "color.accent": accent_ref}


def _recolored(value: Any, colors: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _recolored(v, colors) for k, v in value.items()}
    if isinstance(value, list):
        return [_recolored(v, colors) for v in value]
    return colors.get(value, value) if isinstance(value, str) else value


def _name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise Refused(f"{name!r} is not a hand set name: letters, digits and _, "
                      "not starting with a digit")
    return name


def add_hand_set(index: SpanIndex, name: str, preset: str) -> Patch:
    """Add the preset ``preset`` as the hand set ``name``, in the face's
    colours; when no element places a hand set yet, a `hands` element at
    the centre places this one."""
    _name(name)
    if preset not in presets():
        raise Refused(f"there is no preset called {preset}: {', '.join(presets())}")
    if name in _sets(index):
        raise Refused(f"there is a hand set called {name} already")
    value = _recolored(copy.deepcopy(presets()[preset]), _face_colors(index))
    patch = set_value(index, ("resources", "hand_sets", name), value, block=True)
    placed = any(placed_by(index, n) for n in _sets(index))
    if not placed:
        patch = chain(patch, lambda i: add(i, "hands", choice=name))
    return Patch(patch.text, patch.expected,
                 f"add the hand set {name} ({preset})" + ("" if placed else ", placed at the centre"))


def duplicate_hand_set(index: SpanIndex, name: str) -> Patch:
    """A copy of the hand set ``name`` as `<name>_copy` (or `_copy2`, ...)."""
    sets = _sets(index)
    if name not in sets:
        raise Refused(f"there is no hand set called {name}")
    new = next(f"{name}_copy{'' if n == 1 else n}" for n in range(1, 1000)
               if f"{name}_copy{'' if n == 1 else n}" not in sets)
    patch = set_value(index, ("resources", "hand_sets", new), copy.deepcopy(sets[name]),
                      block=True)
    return Patch(patch.text, patch.expected, f"duplicate the hand set {name} as {new}")


def rename_hand_set(index: SpanIndex, old: str, new: str) -> Patch:
    """Rename a hand set and every element's `set: <old>`."""
    if old not in _sets(index):
        raise Refused(f"there is no hand set called {old}")
    _name(new)
    if new in _sets(index):
        raise Refused(f"there is a hand set called {new} already")
    patch = chain(rename_key(index, ("resources", "hand_sets", old), new),
                  lambda i: _ended_patch(i, _repoint, "set", old, new))
    return Patch(patch.text, patch.expected, f"rename the hand set {old} to {new}")


def delete_hand_set(index: SpanIndex, name: str) -> Patch:
    """Delete a hand set. Refused while an element places it."""
    if name not in _sets(index):
        raise Refused(f"there is no hand set called {name}")
    placing = placed_by(index, name)
    if placing:
        raise Refused(f"{', '.join(placing)} {'places' if len(placing) == 1 else 'place'} "
                      f"the hand set {name}: delete {'it' if len(placing) == 1 else 'them'} "
                      "or point them at another set first")
    path: Path = ("resources", "hand_sets", name)
    patch = remove(index, path)
    return Patch(patch.text, patch.expected, f"delete the hand set {name}")


def summary_names(index: SpanIndex) -> list[str]:
    """The declared hand sets' names."""
    return [str(n) for n in _sets(index)]


def summary(index: SpanIndex) -> list[dict[str, Any]]:
    """Each hand set: its hands (parts and colour) and the elements placing
    it, for the Face panel."""
    out = []
    for name, entry in _sets(index).items():
        entry = entry if isinstance(entry, dict) else {}
        hands = {h: {"parts": len((entry[h] or {}).get("parts") or []),
                     "color": (entry[h] or {}).get("color")}
                 for h in HANDS if isinstance(entry.get(h), dict)}
        held = index[("resources", "hand_sets", name)]
        last = index.text.count("\n", 0, max(index.value_end(held) - 1, 0)) + 1
        out.append({"name": str(name), "hands": hands, "placed_by": placed_by(index, str(name)),
                    "line": held.key.start_mark.line + 1, "end": last})
    return out
