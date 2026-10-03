"""Colour-scheme edits: each changes every place a scheme or a role is
written, as one patch.

A scheme edit one key at a time is refused by the gate, rightly: every
scheme must declare the same roles, a style entry names its scheme, and a
role is referenced as `color.<role>` anywhere in the face. So each edit
here is a `chain` of the keys it must change together:

- `make_switchable`: chosen palette colours become the roles of a first
  scheme, under the same names, so no reference changes; a style entry
  picks the scheme;
- `add_scheme`: a copy of another scheme, and the style entries that
  reach it;
- `rename_scheme`, `delete_scheme`: the key and every style entry naming it;
- `add_role`, `rename_role`, `delete_role`: the role in every scheme, and
  for a rename every `color.<role>`;
- `remove_theme`: the kept scheme's roles become palette colours of the
  same names, `theme:` goes, and every style entry loses its `scheme:`.
  An entry left with nothing (it named only a scheme) goes; one naming a
  layout stays, even when that leaves two alike (the author's to resolve).
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .colors import hex_of, roles, swatches, users
from .patch import Patch, chain, remove, rename_key, rewrite_scalars, set_value
from .spans import Path, Refused, SpanIndex

Step = Callable[[SpanIndex], Patch]


def _data(index: SpanIndex) -> dict[str, Any]:
    return index.data if isinstance(index.data, dict) else {}


def _schemes(index: SpanIndex) -> dict[str, Any]:
    schemes = (_data(index).get("theme") or {}).get("schemes") or {}
    return schemes if isinstance(schemes, dict) else {}


def _style(index: SpanIndex) -> dict[str, Any] | None:
    style = (_data(index).get("config") or {}).get("style")
    return style if isinstance(style, dict) else None


def _entries(index: SpanIndex) -> dict[str, Any]:
    style = _style(index)
    choices = (style or {}).get("choices") or {}
    return choices if isinstance(choices, dict) else {}


def _run(index: SpanIndex, steps: list[Step], what: str) -> Patch:
    """``steps`` as one patch, each on the text the one before left."""
    if not steps:
        raise Refused(f"{what}: nothing to change")
    patch = steps[0](index)
    for step in steps[1:]:
        patch = chain(patch, step)
    return Patch(patch.text, patch.expected, what)


def _set(path: Path, value: Any, block: bool = False) -> Step:
    return lambda i: set_value(i, path, value, block=block)


def _remove(path: Path) -> Step:
    return lambda i: remove(i, path)


def _rename(path: Path, new: str) -> Step:
    return lambda i: rename_key(i, path, new)


def _name(name: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise Refused(f"{name!r} is not a {what} name: letters, digits and _, "
                      "not starting with a digit")
    return name


def _scheme(index: SpanIndex, name: str) -> dict[str, Any]:
    scheme = _schemes(index).get(name)
    if not isinstance(scheme, dict):
        raise Refused(f"there is no scheme called {name}")
    return scheme


def _role_value(index: SpanIndex, value: Any) -> str:
    """A role's colour as written for a scheme: a swatch reference stays,
    anything else is a hex value."""
    if isinstance(value, str) and value.startswith("color."):
        if value[6:] not in swatches(index):
            raise Refused(f"{value} is not a palette colour: a scheme's colour must be "
                          "known when the face is built")
        return value
    return hex_of(value)


# -- schemes ------------------------------------------------------------------

def make_switchable(index: SpanIndex, names: list[str], scheme: str) -> Patch:
    """Move the palette colours ``names`` into a first scheme, ``scheme``,
    as roles of the same names; a style entry (or every existing one)
    picks it."""
    _name(scheme, "scheme")
    if _schemes(index):
        raise Refused("the face has schemes already: add a scheme instead")
    held = swatches(index)
    if not names:
        raise Refused("pick the colours that should change with the style")
    missing = [n for n in names if n not in held]
    if missing:
        raise Refused(f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                      "not a palette colour")
    steps: list[Step] = [_remove(("resources", "palette", n)) for n in names]
    steps.append(_set(("theme",), {"schemes": {scheme: {"colors": {n: held[n] for n in names}}}},
                      block=True))
    entries = _entries(index)
    if not entries:
        steps.append(_set(("config", "style"),
                          {"default": scheme, "choices": {scheme: {"scheme": scheme}}},
                          block=True))
    else:
        steps += [_set(("config", "style", "choices", e, "scheme"), scheme) for e in entries]
    return _run(index, steps, f"make {', '.join(names)} switchable, in the scheme {scheme}")


def add_scheme(index: SpanIndex, name: str, like: str | None = None) -> Patch:
    """A new scheme, a copy of ``like`` (the first scheme by default), and
    the style entries that reach it: one, when every entry names only a
    scheme; else one per layout, `<layout>_<name>`."""
    _name(name, "scheme")
    schemes = _schemes(index)
    if not schemes:
        raise Refused("the face has no schemes yet: make colours switchable first")
    if name in schemes:
        raise Refused(f"there is a scheme called {name} already")
    source = _scheme(index, like or next(iter(schemes)))
    steps: list[Step] = [_set(("theme", "schemes", name),
                              {"colors": dict(source.get("colors") or {})})]
    entries = _entries(index)
    layouts = list(dict.fromkeys(e["layout"] for e in entries.values()
                                 if isinstance(e, dict) and e.get("layout")))
    if layouts:
        for layout in layouts:
            entry = f"{layout}_{name}"
            if entry in entries:
                raise Refused(f"there is a style called {entry} already")
            steps.append(_set(("config", "style", "choices", entry),
                              {"layout": layout, "scheme": name}))
    else:
        if name in entries:
            raise Refused(f"there is a style called {name} already")
        steps.append(_set(("config", "style", "choices", name), {"scheme": name}))
    return _run(index, steps, f"add the scheme {name}")


def rename_scheme(index: SpanIndex, old: str, new: str) -> Patch:
    """Rename a scheme and every style entry's `scheme:` naming it."""
    _scheme(index, old)
    _name(new, "scheme")
    if new in _schemes(index):
        raise Refused(f"there is a scheme called {new} already")
    steps: list[Step] = [_rename(("theme", "schemes", old), new)]
    steps += [_set(("config", "style", "choices", e, "scheme"), new)
              for e, entry in _entries(index).items()
              if isinstance(entry, dict) and entry.get("scheme") == old]
    return _run(index, steps, f"rename the scheme {old} to {new}")


def delete_scheme(index: SpanIndex, name: str) -> Patch:
    """Delete a scheme and the style entries naming it. Refused for the last
    scheme (remove the schemes instead) and when no style entry would be
    left."""
    _scheme(index, name)
    if len(_schemes(index)) == 1:
        raise Refused(f"{name} is the only scheme: remove the schemes instead")
    entries = _entries(index)
    gone = [e for e, entry in entries.items()
            if isinstance(entry, dict) and entry.get("scheme") == name]
    if gone and len(gone) == len(entries):
        raise Refused(f"every style picks {name}: point one at another scheme first")
    steps: list[Step] = [_remove(("config", "style", "choices", e)) for e in gone]
    style = _style(index) or {}
    if style.get("default") in gone:
        steps.append(_set(("config", "style", "default"),
                          next(e for e in entries if e not in gone)))
    steps.append(_remove(("theme", "schemes", name)))
    return _run(index, steps, f"delete the scheme {name}"
                + (f" and the styles {', '.join(gone)}" if gone else ""))


def remove_theme(index: SpanIndex, keep: str) -> Patch:
    """Remove every scheme, keeping ``keep``'s colours as palette colours
    named after their roles; every style entry loses its `scheme:`."""
    kept = _scheme(index, keep)
    held = swatches(index)
    steps: list[Step] = []
    for role, value in (kept.get("colors") or {}).items():
        if isinstance(value, str) and value.startswith("color."):
            value = held.get(value[6:], value)
        steps.append(_set(("resources", "palette", role), hex_of(value), block=True))
    steps.append(_remove(("theme",)))
    entries = _entries(index)
    left = [e for e, entry in entries.items() if isinstance(entry, dict) and entry.get("layout")]
    if entries and not left:
        steps.append(_remove(("config", "style")))
    else:
        for e, entry in entries.items():
            if not isinstance(entry, dict) or "scheme" not in entry:
                continue
            steps.append(_remove(("config", "style", "choices", e, "scheme")) if e in left
                         else _remove(("config", "style", "choices", e)))
        if left and (_style(index) or {}).get("default") not in left:
            steps.append(_set(("config", "style", "default"), left[0]))
    return _run(index, steps, f"remove the schemes, keeping {keep}'s colours")


# -- roles --------------------------------------------------------------------

def add_role(index: SpanIndex, name: str, values: dict[str, Any] | Any) -> Patch:
    """A new role in every scheme: ``values`` maps each scheme to its
    colour, or is one colour for all."""
    _name(name, "role")
    schemes = _schemes(index)
    if not schemes:
        raise Refused("the face has no schemes yet: make colours switchable first")
    if name in roles(index):
        raise Refused(f"there is a role called {name} already")
    if name in swatches(index):
        raise Refused(f"{name} is a palette colour: a role needs a name of its own")
    each = values if isinstance(values, dict) else {s: values for s in schemes}
    missing = [s for s in schemes if s not in each]
    if missing:
        raise Refused(f"no colour for {name} in {', '.join(missing)}")
    steps = [_set(("theme", "schemes", s, "colors", name), _role_value(index, each[s]))
             for s in schemes]
    return _run(index, steps, f"add the role {name}")


def rename_role(index: SpanIndex, old: str, new: str) -> Patch:
    """Rename a role in every scheme and every `color.<old>` with it."""
    _name(new, "role")
    schemes = _schemes(index)
    if not any(old in (s.get("colors") or {}) for s in schemes.values()):
        raise Refused(f"there is no role called {old}")
    if new in roles(index) or new in swatches(index):
        raise Refused(f"{new} names a colour already")
    pattern = re.compile(rf"(?<![A-Za-z0-9_.])color\.{re.escape(old)}(?![A-Za-z0-9_])")
    steps: list[Step] = [_rename(("theme", "schemes", s, "colors", old), new) for s in schemes]
    steps.append(lambda i: rewrite_scalars(i, lambda t: pattern.sub(f"color.{new}", t),
                                           f"refer to color.{new}"))
    return _run(index, steps, f"rename the role {old} to {new}")


def delete_role(index: SpanIndex, name: str) -> Patch:
    """Delete a role from every scheme. Refused while something uses it,
    and for a scheme's last role."""
    schemes = _schemes(index)
    if not any(name in (s.get("colors") or {}) for s in schemes.values()):
        raise Refused(f"there is no role called {name}")
    used = users(index, name)
    if used:
        raise Refused(f"color.{name} is used by {len(used)} key"
                      f"{'s' if len(used) > 1 else ''}: point them at another colour first")
    if any(len(s.get("colors") or {}) == 1 for s in schemes.values()):
        raise Refused(f"{name} is the only role: remove the schemes instead")
    return _run(index, [_remove(("theme", "schemes", s, "colors", name)) for s in schemes],
                f"delete the role {name}")
