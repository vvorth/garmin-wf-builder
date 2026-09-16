"""Terminal presentation: whether to colour a stream, and the styles used.

Colour is decided per stream, so ``wfb build 2>log`` still colours stdout on a
terminal while the log stays plain.  The precedence, highest first:

1. ``--color always|never`` on the command line (`set_mode`);
2. ``NO_COLOR`` set to anything non-empty disables colour (no-color.org);
3. ``FORCE_COLOR`` or ``CLICOLOR_FORCE`` set to anything non-empty enables it;
4. otherwise colour only a TTY whose ``TERM`` is not ``dumb``.

Nothing here changes *what* is printed, only how it looks: with colour off
every helper returns its text unchanged, so piped output and tests see plain
text.
"""

from __future__ import annotations

import os
import shutil
from typing import TextIO

MODES = ("auto", "always", "never")

_mode = "auto"

_RESET = "\033[0m"
_CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}


def set_mode(mode: str) -> None:
    """Set the process-wide colour mode: ``auto``, ``always`` or ``never``."""
    global _mode
    if mode not in MODES:
        raise ValueError(f"colour mode must be one of {', '.join(MODES)}, not {mode!r}")
    _mode = mode


def get_mode() -> str:
    return _mode


def should_color(stream: TextIO) -> bool:
    """Whether text written to ``stream`` should carry ANSI colour."""
    if _mode == "always":
        return True
    if _mode == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except ValueError:  # a closed stream
        return False


def is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except ValueError:
        return False


def width(stream: TextIO, default: int = 100) -> int | None:
    """The terminal width to wrap prose at, or ``None`` for "do not wrap".

    Only a real terminal is wrapped: piped output keeps one logical line per
    line, which is what grep and an LLM reading the log both want.
    """
    if not is_tty(stream):
        return None
    return max(60, shutil.get_terminal_size((default, 24)).columns)


def style(text: str, *names: str, enabled: bool) -> str:
    """Wrap ``text`` in the named SGR styles when ``enabled``; else return it as is."""
    if not enabled or not names or not text:
        return text
    codes = ";".join(_CODES[name] for name in names)
    return f"\033[{codes}m{text}{_RESET}"


#: Severity -> styles, shared by diagnostics and the CLI's summary counts.
SEVERITY_STYLE = {
    "error": ("bold", "red"),
    "warning": ("bold", "yellow"),
    "note": ("bold", "cyan"),
}
