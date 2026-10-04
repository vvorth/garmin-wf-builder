"""The author's names for what the compiler calls something else.

The IR builder reads the internal shape `wfb/lower.py` produces, whose key
and kind names are older than format 2's.  A diagnostic names what the
author wrote, so every message that names a key, a kind or a colour
reference goes through here.
"""

from __future__ import annotations

from typing import Iterable

#: Internal key -> the key a format 2 author writes.
KEYS = {
    "format": "text",
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
