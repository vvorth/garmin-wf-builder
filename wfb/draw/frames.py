"""Which elements a frame draws: one answer for the generated view, its read
plan and the preview.

A frame is the awake `active` one, the MIP `low_power` one, or the AMOLED
always-on `aod` one.  The awake and low-power frames draw an element whose
`modes` name them; the always-on frame draws every element whose resolved
`aod:` is set, whatever its modes.  A group draws nothing itself.

The Styles layout switch is a second, separate question (`in_layout`): the
view guards an element of another layout at runtime, and the preview,
which renders one layout, leaves it out.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..layout import Placed


def frame_members(items: Iterable["Placed"], frame: str) -> list["Placed"]:
    """The elements of ``items`` that ``frame`` draws, in their order."""
    if frame == "aod":
        return [p for p in items if p.kind != "group" and p.element.aod is not None]
    return [p for p in items if p.kind != "group" and frame in p.element.modes]


def in_layout(placed: "Placed", layout: str | None) -> bool:
    """Whether ``placed`` draws while ``layout`` is the active Styles layout
    (`None`: no `layouts:`, or a colour-only entry): shared content always
    does, a layout's own content only under its layout."""
    return placed.element.layout is None or placed.element.layout == layout
