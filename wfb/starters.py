"""The face templates a new design starts from: `wfb new` and the editor's
New both copy one through :func:`instantiate`, so they cannot drift."""

from __future__ import annotations

import uuid
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

TEMPLATE_BLURB = {
    "minimal": "a background and the time -- the smallest face worth building",
    "dashboard": "time, a goal ring, two data clusters and a battery bar",
    "analog": "a three-hand dial with ticks, numerals and a date window",
    "sport": "time, a heart-rate graph and four readouts, distance in the wearer's units",
    "gauge": "a battery needle gauge over the top half, the time below it",
    "calendar": "the time over a Monday-first month of dots, today lit",
    "themed": "light/dark schemes, accent colours and two complication slots set on the watch",
    "amoled": "adds an AMOLED target, with a sparse always-on sleep frame",
    "palette": "all 64 MIP colours as named swatches, with a colour scheme and colour axes",
}


class UnknownTemplate(ValueError):
    """A template name that is not one of `names()`."""


def names() -> list[str]:
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.yaml"))


def instantiate(template: str, name: str) -> str:
    """The template's text with a fresh UUID and ``name`` substituted.

    Two faces sharing a UUID are the same app to the watch -- installing the
    second replaces the first -- so every call mints its own.  ``template``
    is a name, never a path: joined unchecked, `../x` or an absolute path
    would read any .yaml on disk."""
    if template not in names():
        raise UnknownTemplate(f"no template {template!r}")
    source = TEMPLATE_DIR / f"{template}.yaml"
    return (
        source.read_text(encoding="utf-8")
        .replace("__UUID__", str(uuid.uuid4()))
        .replace("__NAME__", name)
    )
