"""The icon catalogue.

ADR 0004 prefers ``icon`` over ``image``: an icon is drawn from ``Dc``
primitives by a support-barrel function rather than shipped as a bitmap, so it
costs no resource memory, scales to any device without a per-family asset, and
takes its colour at runtime.  The barrel only decides *how* to draw a named
shape; the generator still decides *what* is drawn and where (ADR 0003).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Icon:
    name: str
    #: The support-barrel function that draws it, given (dc, cx, cy, size).
    function: str
    description: str


CATALOG: dict[str, Icon] = {
    icon.name: icon
    for icon in [
        Icon("steps", "WfbIcons.drawSteps", "two offset footprints"),
        Icon("heart", "WfbIcons.drawHeart", "a heart outline, for heart rate"),
        Icon("flame", "WfbIcons.drawFlame", "a flame, for calories"),
        Icon("alarm", "WfbIcons.drawAlarm", "an alarm clock, for an alarm indicator"),
        Icon("dnd", "WfbIcons.drawDnd", "a bell with a slash, for do-not-disturb"),
        Icon("notification", "WfbIcons.drawNotification",
             "a speech-bubble badge; draw a count on top of it"),
    ]
}


def get(name: str) -> Icon | None:
    return CATALOG.get(name)


def names() -> list[str]:
    return sorted(CATALOG)
