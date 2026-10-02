"""What the canvas lets the author drag, and a drag turned into an edit.

The handles of a placed element follow from what `wfb.edit.geometry` can
write back for it, so a handle never offers a drag the engine refuses:

- the element itself: `move` (its `at:`; a line's `to:` with it);
- a line's two ends: `move` of one `part`;
- `size:` width and height: `resize`, on the edge that moves when the size
  grows, given the element's alignment (`wfb.layout.alignment_shift`): a
  left-aligned box grows to the right, a centred one both ways, so dragging
  its right edge by one pixel is two pixels of width (`gain`);
- `radius:`: `resize`, on the circle's right;
- an arc's `start_angle` and `sweep`: `turn`, at the arc's two ends.

All coordinates are device pixels.
"""

from __future__ import annotations

import math
from typing import Any

from ..edit.geometry import ANGLES, EXTENTS
from ..layout import Placed
from ..units import Length

#: `align`'s horizontal and `vertical_align`'s values, as the edge a growing
#: box moves: the handle's side and its gain.
_X = {"left": ("right", 1), "center": ("right", 2), "right": ("left", -1)}
_Y = {"top": ("bottom", 1), "center": ("bottom", 2), "bottom": ("top", -1)}


def _length(element: Any, *path: str) -> Length | None:
    value: Any = element
    for step in path:
        value = getattr(value, step, None)
    return value if isinstance(value, Length) else None


def handles(placed: Placed) -> list[dict[str, Any]]:
    """The handles of ``placed`` beyond moving it whole."""
    element = placed.element
    out: list[dict[str, Any]] = []
    if getattr(element, "shape", None) == "line":
        ex, ey = getattr(placed, "end")
        out.append({"kind": "end", "part": "at", "x": placed.center[0], "y": placed.center[1]})
        out.append({"kind": "end", "part": "to", "x": ex, "y": ey})
        return out
    if getattr(element, "shape", None) == "polygon":
        return out
    box = placed.inner_box
    cx, cy = placed.center
    width, height = _length(element, "size", "width"), _length(element, "size", "height")
    if width is not None and ("size", "width") in EXTENTS:
        side, gain = _X.get(str(getattr(element, "align", "center")), ("right", 2))
        x = box.x + box.width if side == "right" else box.x
        out.append({"kind": "size", "key": ["size", "width"], "axis": "x", "gain": gain,
                    "x": x, "y": box.y + box.height // 2})
    if height is not None:
        side, gain = _Y.get(str(getattr(element, "vertical_align", "center")), ("bottom", 2))
        y = box.y + box.height if side == "bottom" else box.y
        out.append({"kind": "size", "key": ["size", "height"], "axis": "y", "gain": gain,
                    "x": box.x + box.width // 2, "y": y})
    radius = getattr(placed, "radius", None)
    if _length(element, "radius") is not None and isinstance(radius, int) and radius > 0:
        out.append({"kind": "size", "key": ["radius"], "axis": "x", "gain": 1,
                    "x": cx + radius, "y": cy})
        start, sweep = getattr(placed, "start_angle", None), getattr(placed, "sweep", None)
        # the rule `turn` applies: among shapes only an arc has angles
        if start is not None and sweep is not None and all(
                hasattr(element, k) for k in ANGLES) and abs(float(sweep)) < 360 \
                and getattr(element, "shape", "arc") == "arc":
            for key, degrees in (("start_angle", float(start)),
                                 ("sweep", float(start) + float(sweep))):
                theta = math.radians(degrees)
                out.append({"kind": "angle", "key": key, "cx": cx, "cy": cy,
                            "start": float(start), "sweep": float(sweep),
                            "x": round(cx + radius * math.sin(theta)),
                            "y": round(cy - radius * math.cos(theta))})
    return out


def describe(gesture: dict[str, Any], element_id: str, device: str) -> str:
    """A drag in the author's terms, for the history: "move clock by (+6,
    -3) px on fr955"."""
    kind = gesture.get("kind")
    if kind == "move":
        what = element_id if gesture.get("part", "both") == "both" else \
            f"{element_id}'s {'start' if gesture['part'] == 'at' else 'end'}"
        return f"move {what} by ({gesture['dx']:+d}, {gesture['dy']:+d}) px on {device}"
    if kind == "resize":
        key = ".".join(gesture["key"])
        return f"resize {element_id}.{key} by {gesture['delta']:+d} px on {device}"
    return f"turn {element_id}.{gesture.get('key')} to {gesture.get('degrees'):g}° on {device}"
