"""The author's names for what the compiler calls something else.

The IR builder reads the internal shape `wfb/lower.py` produces, whose key
and kind names are older than format 2's.  A diagnostic names what the
author wrote, so every message that names a key, a kind or a colour
reference goes through here.
"""

from __future__ import annotations

import re
from typing import Iterable

#: Internal key -> the key a format 2 author writes.
KEYS = {
    "format": "text",
    "color_scheme": "theme: schemes:",
}

#: Internal element kind (or shape) -> the `type:` a format 2 author writes.
KINDS = {
    "progress": "gauge",
    "complication_slot": "data",
    "rounded_rectangle": "rectangle",
}


def key(name: str, *, text_value: bool = False) -> str:
    """The author's name for internal key ``name``.  ``text_value``: the key
    is a text element's (or text part's) ``value:``, which format 2 writes
    inside ``text:``."""
    if name == "value" and text_value:
        return "text"
    return KEYS.get(name, name)


def keys(names: Iterable[str], *, text_value: bool = False) -> list[str]:
    """The author's names for ``names``, sorted, each once."""
    return sorted({key(name, text_value=text_value) for name in names})


def kind(name: str) -> str:
    return KINDS.get(name, name)


_REF = re.compile(r"\b(?:palette|config\.colors)\.([A-Za-z_][A-Za-z0-9_]*)"
                  r"|\bconfig\.(accent_color|data_color)\b"
                  r"|\bconfig\.data\.([A-Za-z_][A-Za-z0-9_]*)")


def refs(text: str) -> str:
    """``text`` with every internal colour or slot reference named the way
    the author writes it: ``palette.x``/``config.colors.x`` -> ``color.x``,
    ``config.accent_color`` -> ``color.accent`` (the axis's default role),
    ``config.data.x`` -> ``x``."""
    def one(match: re.Match[str]) -> str:
        if match.group(1):
            return f"color.{match.group(1)}"
        if match.group(2):
            return "color.accent" if match.group(2) == "accent_color" else "color.data"
        return match.group(3)
    return _REF.sub(one, text)


def absent(element: object) -> str:
    """An element's absence policy as the author writes it: ``absent:
    hide``, ``absent: "--"`` (a placeholder) or ``absent: {value: ...}``
    (a fallback reading).  Generated code comments quote this."""
    policy = getattr(element, "absent", None) or "hide"
    if policy == "placeholder":
        return f'absent: "{getattr(element, "placeholder", "")}"'
    if policy == "fallback":
        fallback = getattr(element, "fallback", None)
        shown = getattr(fallback, "shown", "...")
        return f"absent: {{value: {shown}}}"
    return f"absent: {policy}"
