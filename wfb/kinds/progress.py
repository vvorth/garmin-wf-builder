"""`type: progress` -- a bound fraction, drawn as an arc or a bar."""

from __future__ import annotations

from ..ir.model import Progress
from ..layout import PlacedProgress, Resolver
from ..preview import _Renderer
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import _article
from . import ElementKind

#: Keys that only make sense for one `progress` style.  Supplying one set
#: while declaring the other style is a much commoner mistake than omitting
#: a key, and "missing required key 'size'" does not begin to explain it.
PROGRESS_STYLE_KEYS = {
    "arc": ("radius", "thickness", "start_angle", "sweep"),
    "bar": ("size",),
}


def precheck(doc, bag, element: dict) -> bool:
    """Catch a `progress` whose keys belong to the other style."""
    if element.get("type") != "progress":
        return False
    style = element.get("style")
    if style not in PROGRESS_STYLE_KEYS:
        return False
    other = "bar" if style == "arc" else "arc"
    wrong = [key for key in PROGRESS_STYLE_KEYS[other] if key in element]
    if not wrong:
        return False
    missing = [key for key in PROGRESS_STYLE_KEYS[style] if key not in element]
    if not missing:
        return False
    plural = "s" if len(wrong) > 1 else ""
    bag.error(
        "schema",
        f"this progress element is 'style: {style}' but carries "
        f"{other}-only key{plural}: {', '.join(repr(k) for k in wrong)}",
        doc.span(element, "style"),
        notes=[
            f"either set 'style: {other}', or replace those with "
            f"{', '.join(repr(k) for k in PROGRESS_STYLE_KEYS[style])}",
            "'arc' is a stroked ring -- radius, thickness, start_angle, sweep; "
            "'bar' is a rectangle -- size",
        ],
    )
    return True


def circular_extent(placed: PlacedProgress):
    if placed.element.style == "arc":
        return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
    return None


def describe(placed: PlacedProgress) -> str:
    return _article(f"{placed.element.style} progress indicator")


KIND = ElementKind(
    name="progress",
    ir_class=Progress,
    placed_class=PlacedProgress,
    build=lambda b, node, common, path: b._build_progress(node, common),
    resolve=Resolver._resolve_progress,
    precheck=precheck,
    antialiased=True,
    circular_extent=circular_extent,
    draw_preview=_Renderer._progress,
    emit_draw=lambda w, resolved, placed, value_guards, plan, aod: shapes._emit_progress(
        w, placed, value_guards, aod),
    describe=describe,
    layout_constants=layout_constants_mod._progress_constants,
)
