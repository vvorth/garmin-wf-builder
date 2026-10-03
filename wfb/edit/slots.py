"""A slot added with the element that draws it, as one change: the wearer
picks what a slot shows, but a slot nothing draws shows nothing."""

from __future__ import annotations

import re

from .. import complications
from .patch import Patch, chain, set_value
from .spans import Refused, SpanIndex
from .structure import add


def add_slot(index: SpanIndex, name: str, default: str) -> Patch:
    """Declare the `config: slots:` entry ``name``, showing ``default``
    until the wearer picks and offering every type (`choices: any`), and
    add a `data` element drawing it at the end of `elements:`."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise Refused(f"{name!r} is not a slot name: letters, digits and _, "
                      "not starting with a digit")
    if default not in complications.TYPES:
        raise Refused(f"{default!r} is not a complication type: see `wfb complications`")
    data = index.data if isinstance(index.data, dict) else {}
    if name in (((data.get("config") or {}).get("slots")) or {}):
        raise Refused(f"there is a slot called {name} already")
    patch = set_value(index, ("config", "slots", name), {"default": default, "choices": "any"},
                      block=True)
    patch = chain(patch, lambda i: add(i, "data", choice=name))
    return Patch(patch.text, patch.expected,
                 f"add the slot {name}, showing {complications.label(default)}, and draw it")
