"""Colour edits: a picked colour becomes a named palette swatch.

The editor's picker offers the face's own swatches and roles, the 64 named
MIP colours (`wfb.palette.MIP64_NAMED`) and any custom colour. Whatever is
picked, the element names a swatch (`color.<name>`), never a bare literal:

- a colour the palette already holds reuses that swatch, whatever its name;
- one of the 64 is added under its MIP name, with its label;
- any other colour is added as `c` plus its hex: `#FF8000` is `cFF8000`.

A name taken by another colour, or by a role, gets `_2`, `_3`, ...

A swatch named after its own value (`cFF8000`, or the MIP name of its
colour, with or without that suffix) is the editor's *automatic* swatch.
Picking another colour for the last element that used one removes it in
the same patch, and changing its value in the Colours section renames it
to match. A swatch with a name of the author's own is never renamed or
removed by either.

The picker on an element only re-points that element's key; a swatch's
value changes only through `set_swatch`, which reaches every user.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from ..palette import MIP64_NAMED, Color, ColorError, mip64_name
from .patch import Patch, chain, remove, rename_reference, set_value
from .spans import Path, Refused, SpanIndex, dotted

#: A whole `color.<name>` reference, inside an expression too.
REFERENCE = re.compile(r"(?<![A-Za-z0-9_.])color\.([A-Za-z_][A-Za-z0-9_]*)(?![A-Za-z0-9_])")

#: Swatches the launcher icon reads by name (`wfb.emit.resources.launcher_icon`),
#: so a face uses them even where no `color.<name>` does.
LAUNCHER = frozenset({"bg", "accent", "text", "fg"})

_LABELS = {name: label for name, _, label in MIP64_NAMED}
_SUFFIX = re.compile(r"_\d+$")


def hex_of(value: Any) -> str:
    """``value`` as `#RRGGBB`, upper case; `Refused` when it is no colour."""
    try:
        return str(Color.parse(value))
    except ColorError as exc:
        raise Refused(str(exc)) from None


def _palette(index: SpanIndex) -> dict[str, Any]:
    data = index.data if isinstance(index.data, dict) else {}
    palette = (data.get("resources") or {}).get("palette") or {}
    return palette if isinstance(palette, dict) else {}


def swatches(index: SpanIndex) -> dict[str, str]:
    """Every swatch whose value is a colour: name -> `#RRGGBB`."""
    out = {}
    for name, entry in _palette(index).items():
        raw = entry.get("value") if isinstance(entry, dict) else entry
        try:
            out[str(name)] = str(Color.parse(raw))
        except ColorError:
            continue
    return out


def roles(index: SpanIndex) -> list[str]:
    """Every role: each scheme's, then the colour axes' (`accent`, `data`,
    or the axis's own `role:`)."""
    data = index.data if isinstance(index.data, dict) else {}
    out: list[str] = []
    for scheme in (((data.get("theme") or {}).get("schemes")) or {}).values():
        for role in ((scheme or {}).get("colors") or {}):
            if role not in out:
                out.append(str(role))
    config = data.get("config") or {}
    for axis, default in (("accent_color", "accent"), ("data_color", "data")):
        if isinstance(config.get(axis), dict):
            role = str(config[axis].get("role") or default)
            if role not in out:
                out.append(role)
    return out


def automatic_name(value: str) -> str:
    """The name the editor gives a colour: its MIP name, else `c` + hex."""
    v = hex_of(value)
    return mip64_name(v) or "c" + v[1:]


def is_automatic(name: str, value: str) -> bool:
    """Whether ``name`` is the editor's own name for ``value``."""
    return _SUFFIX.sub("", name) == automatic_name(value)


def _fresh(index: SpanIndex, base: str) -> str:
    taken = set(_palette(index)) | set(roles(index))
    if base not in taken:
        return base
    return next(f"{base}_{n}" for n in range(2, 10_000) if f"{base}_{n}" not in taken)


def _walk(data: Any, path: Path) -> list[tuple[Path, str]]:
    if isinstance(data, dict):
        return [hit for k, v in data.items() for hit in _walk(v, path + (k,))]
    if isinstance(data, list):
        return [hit for i, v in enumerate(data) for hit in _walk(v, path + (i,))]
    return [(path, data)] if isinstance(data, str) else []


def users(index: SpanIndex, name: str) -> list[Path]:
    """The path of every string value that names `color.<name>`."""
    return [path for path, text in _walk(index.data, ())
            if any(m.group(1) == name for m in REFERENCE.finditer(text))]


def user_names(index: SpanIndex, name: str) -> list[str]:
    """Who uses `color.<name>`, as the author knows them: the id of the
    element holding each reference, else the reference's dotted path."""
    elements = {e.path: e.name for e in index.elements()}
    out: list[str] = []
    for path in users(index, name):
        holder = next((elements[path[:n]] for n in range(len(path), 0, -1)
                       if path[:n] in elements), None)
        shown = holder or dotted(path)
        if shown not in out:
            out.append(shown)
    return out


def _value_path(index: SpanIndex, name: str) -> Path:
    entry = _palette(index).get(name)
    return ("resources", "palette", name) + (("value",) if isinstance(entry, dict) else ())


def _swatch_for(index: SpanIndex, value: str) -> tuple[str, Patch | None]:
    """The swatch holding ``value``: an existing one, or a new one and the
    patch adding it."""
    v = hex_of(value)
    for name, held in swatches(index).items():
        if held == v:
            return name, None
    name = _fresh(index, automatic_name(v))
    mip = mip64_name(v)
    entry: Any = {"value": v, "label": _LABELS[mip]} if mip else v
    return name, set_value(index, ("resources", "palette", name), entry)


def _drop_if_unused(patch: Patch, name: str | None, keep: str) -> Patch:
    """``patch``, followed by removing the automatic swatch ``name`` when
    nothing uses it any more."""
    if name is None or name == keep or name in LAUNCHER:
        return patch
    after = SpanIndex(patch.text)
    held = swatches(after).get(name)
    if held is None or not is_automatic(name, held) or users(after, name):
        return patch
    return chain(patch, lambda i: remove(i, ("resources", "palette", name)))


def use_color(index: SpanIndex, path: Path, value: str) -> Patch:
    """Point the key at ``path`` at ``value``: a `color.<name>` as it is,
    a hex through the swatch holding it (added when there is none). The
    automatic swatch the key named before goes when it has no other user."""
    path = tuple(path)
    before: Any = index.data
    for step in path:
        before = before.get(step) if isinstance(before, dict) else None
    match = REFERENCE.fullmatch(before) if isinstance(before, str) else None
    was = match.group(1) if match else None
    ref = REFERENCE.fullmatch(value) if isinstance(value, str) else None
    if ref is not None:
        name, patch = ref.group(1), set_value(index, path, value)
        what = f"set {dotted(path)} to {value}"
    else:
        name, added = _swatch_for(index, value)
        what = f"set {dotted(path)} to color.{name}" + (f" (adds {name})" if added else "")
        patch = (chain(added, lambda i: set_value(i, path, f"color.{name}")) if added
                 else set_value(index, path, f"color.{name}"))
    patch = _drop_if_unused(patch, was, name)
    return Patch(patch.text, patch.expected, what)


def add_swatch(index: SpanIndex, value: str) -> tuple[Patch, str]:
    """Add ``value`` to the palette under the editor's name for it."""
    name, added = _swatch_for(index, value)
    if added is None:
        raise Refused(f"{hex_of(value)} is in the palette already, as {name}")
    return Patch(added.text, added.expected, f"add the colour {name}"), name


def set_swatch(index: SpanIndex, name: str, value: str) -> Patch:
    """Change a swatch's value; every `color.<name>` follows. An automatic
    swatch is renamed to match its new value."""
    held = swatches(index).get(name)
    if held is None:
        raise Refused(f"there is no colour called {name}")
    v = hex_of(value)
    patch = set_value(index, _value_path(index, name), v)
    what = f"set the colour {name} to {v}"
    if name not in LAUNCHER and is_automatic(name, held) and not is_automatic(name, v):
        new = _fresh(SpanIndex(patch.text), automatic_name(v))
        patch = chain(patch, lambda i: rename_reference(
            i, ("resources", "palette", name), new, "color."))
        what += f", renamed {new}"
        # the MIP label came with the name, and goes with it
        entry = _palette(index)[name]
        if isinstance(entry, dict) and entry.get("label") == _LABELS.get(automatic_name(held)):
            label_path = ("resources", "palette", new, "label")
            mip = mip64_name(v)
            patch = chain(patch, lambda i: set_value(i, label_path, _LABELS[mip]) if mip
                          else remove(i, label_path))
    return Patch(patch.text, patch.expected, what)


def remove_unused(index: SpanIndex) -> Patch:
    """Remove every swatch no `color.<name>` names, except those the
    launcher icon reads."""
    unused = [str(n) for n in _palette(index) if n not in LAUNCHER and not users(index, str(n))]
    if not unused:
        raise Refused("every colour in the palette is in use")
    def remover(name: str) -> Callable[[SpanIndex], Patch]:
        return lambda i: remove(i, ("resources", "palette", name))

    patch = remove(index, ("resources", "palette", unused[0]))
    for name in unused[1:]:
        patch = chain(patch, remover(name))
    return Patch(patch.text, patch.expected, f"remove the unused colours {', '.join(unused)}")
