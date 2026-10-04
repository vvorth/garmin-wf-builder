"""Author text as Monkey C source: a string literal, and a comment.

Author text reaches generated source as string literals (what is drawn)
and in comments (a widest rendering, a menu label). A quote or a
backslash breaks a literal, and a line break breaks both: the literal no
longer closes on its line, and the rest of a `//` comment becomes code.
Every such text goes through here. `wfb.lower` refuses a control
character in drawn text before it gets this far; these keep the source
well formed whatever reaches them.
"""

from __future__ import annotations

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _control(char: str) -> bool:
    return ord(char) < 0x20 or ord(char) == 0x7F


def string_literal(value: str) -> str:
    """``value`` as a double-quoted Monkey C string literal. `monkeyc`
    9.2.0 accepts the `\\n`, `\\r`, `\\t` and `\\uXXXX` escapes in a literal
    (a real build, 2026-10-04)."""
    out = []
    for char in value:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif _control(char):
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def comment_text(text: str) -> str:
    """``text`` as it may stand in a `//` comment: on one line, each
    control character written as its escape."""
    return "".join(_ESCAPES[c] if c in "\n\r\t" else f"\\u{ord(c):04x}" if _control(c) else c
                   for c in text)


def control_character(text: str) -> str | None:
    """The first control character in ``text`` (a line break, a tab), as
    its escape, or `None` when there is none."""
    for char in text:
        if _control(char):
            return comment_text(char)
    return None
