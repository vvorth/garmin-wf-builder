"""How a generated comment spells an IR value the author wrote as a key."""

from __future__ import annotations


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
