"""A preview frame as layers: each drawn element alone on a transparent
ground, plus one layer per outlined group's ring, in draw order.

The editor stacks them, and moves or hides one without redrawing the rest.
The whole-frame steps -- the black ground, the AOD pixel mask, the panel's
palette, the bezel and the skin -- run once on the stack (`compose`), never
per layer.

**Stacking reproduces `wfb.preview.render` up to rounding on anti-aliased
edges.**  The watch has no alpha blending (constraint 10): no element reads
the pixels under it except where an anti-aliased edge blends into them, so
drawing in order onto one frame and stacking layers in order agree.  Where an
edge blends, the layer's colour and coverage are recovered from a black and a
white render of it (difference matting), and 8-bit rounding can leave a
channel one level off: research 27 §5.4 measured 28 of 29 example faces
identical, the 29th off by exactly one on its anti-aliased text edges.
`wfb.preview.render` stays the authoritative single-pass frame.

A lowered element's layer also carries its draw program, partly evaluated
for the frame (`wfb.draw.jsonform`), so the editor can redraw it while a
gesture moves one of its `Layout` constants.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageChops, ImageMath

from ..ir.rings import ring_groups

if TYPE_CHECKING:
    from ..devices import FontMetric
    from ..diagnostics import Span
    from ..fonts import fallback
    from ..layout import Placed, ResolvedFace
    from ..preview import PreviewOptions, Renderer
    from .jsonform import FontRef, Tiles


@dataclass(frozen=True)
class Layer:
    """One layer of a frame.  ``id`` is the element's, or `ring:<group id>`
    for an outlined group's ring; ``kind`` the element kind, or `ring`.
    ``image`` is RGBA at the device's native size, or `None` for a layer
    `layers(..., paint=False)` leaves to its JSON.  ``ops`` is the lowered
    element's program as JSON for this frame, `None` for a kind that does
    not lower and for a group ring; ``fonts`` resolves the font ids it
    names, and ``tiles`` (one store for the whole frame) the tiles its runs
    paste."""

    id: str
    kind: str
    span: "Span | None"
    image: Image.Image | None
    ops: list[dict[str, Any]] | None = None
    fonts: dict[str, "FontRef"] = field(default_factory=dict)
    tiles: "Tiles | None" = None


def matte(black: Image.Image, white: Image.Image) -> Image.Image:
    """One layer's RGBA from the same drawing on a black and on a white
    ground: coverage is what the grounds disagree by, colour the black
    render divided by it (exact for any linear blend, up to 8-bit
    rounding)."""
    alpha = ImageChops.subtract(white, black).convert("L").point(lambda v: 255 - v)
    bands = []
    for band in black.split():
        straight = ImageMath.lambda_eval(
            lambda e: e["min"](e["float"](e["b"]) * 255.0 / e["max"](e["float"](e["a"]), 1.0)
                               + 0.5, 255.0),
            b=band, a=alpha)
        bands.append(straight.convert("L"))
    rgba = Image.merge("RGBA", (*bands, alpha))
    clear = Image.new("RGBA", black.size, (0, 0, 0, 0))
    return Image.composite(rgba, clear, alpha.point(lambda v: 255 if v else 0))


def layers(resolved: "ResolvedFace", options: "PreviewOptions | None" = None, *,
           used_faces: "dict[FontMetric, fallback.SystemFace] | None" = None,
           paint_all: bool = True) -> list[Layer]:
    """The frame `wfb.preview.render` draws, as layers in draw order: before
    each outlined group's first member drawn here, that group's ring (the
    same order `Renderer.render_sequence` paints), then the element.

    With ``paint_all`` false, a layer whose JSON a browser draws itself
    (every op in `jsonform.BROWSER_OPS`) is not painted: its ``image`` is
    `None`, which spares painting every element twice."""
    from .. import preview
    from .jsonform import BROWSER_OPS, Tiles, to_json

    options = options or preview.PreviewOptions()
    entry = preview._resolve_style_entry(resolved.face, options.style)
    values = preview.sample_values(resolved, options, entry)
    items = preview.frame_items(resolved, options, entry)
    rings = ring_groups(resolved.face.elements)
    tiles = Tiles()

    def paint(draw: Callable[["Renderer"], None]) -> Image.Image:
        grounds = []
        for ground in ((0, 0, 0), (255, 255, 255)):
            renderer = preview.new_renderer(resolved, options, values, ground, used_faces)
            draw(renderer)
            grounds.append(renderer.image)
        return matte(*grounds)

    out: list[Layer] = []
    for placed in items:
        for ring in rings:
            members = [p for p in items if p.id in ring.ids]
            if not members or members[0] is not placed:
                continue
            outline = ring.group.outline
            assert outline is not None

            def ring_layer(r: "Renderer", ring: Any = ring, members: list[Any] = members) -> None:
                r.render_ring(ring, members)

            out.append(Layer(f"ring:{ring.group.id}", "ring", ring.group.span, paint(ring_layer)))
        def element_layer(r: "Renderer", placed: "Placed" = placed) -> None:
            r.render_element(placed)

        fonts: dict[str, FontRef] = {}
        renderer = preview.new_renderer(resolved, options, values, (0, 0, 0), used_faces)
        ops: list[dict[str, Any]] = []
        if renderer.shows(placed):
            ops, fonts = to_json(renderer, placed, tiles)
        drawn_by_browser = {op["op"] for op in ops} <= BROWSER_OPS
        image = paint(element_layer) if paint_all or not drawn_by_browser else None
        out.append(Layer(placed.id, placed.kind, placed.element.span, image, ops, fonts, tiles))
    return out


def compose(stack: list[Layer], resolved: "ResolvedFace",
            options: "PreviewOptions | None" = None) -> Image.Image:
    """``stack`` over the black ground, then the whole-frame steps
    (`wfb.preview.finish_frame`): the frame `wfb.preview.render` draws, up
    to anti-aliased rounding."""
    from .. import preview

    options = options or preview.PreviewOptions()
    entry = preview._resolve_style_entry(resolved.face, options.style)
    values = preview.sample_values(resolved, options, entry)
    device = resolved.device
    frame = Image.new("RGBA", (device.width, device.height), (0, 0, 0, 255))
    for layer in stack:
        assert layer.image is not None, "compose needs every layer painted"
        frame = Image.alpha_composite(frame, layer.image)
    return preview.finish_frame(frame.convert("RGB"), resolved, options, values)
