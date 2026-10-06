"""Backend 3: a draw program as JSON for one frame, and a reference
rasteriser of that JSON.

`to_json` partly evaluates an element's program for the frame being painted:
every reading, colour, string and always-on choice is folded to its value,
and every `Layout` constant stays named beside its value
(``{"const": "CLOCK_X", "value": 130, "add": -1}``), so an editor can redraw
the layer with a dragged constant changed.  Nothing in the JSON needs the
design, the expression language or the barrel: an arc carries the
`dc.drawArc` call its `WfbArc.drawSpan` makes, and a text call names its
font by an id the layer's ``fonts`` table resolves.

Text and icons are laid out here, not by the reader: every `text` and
`glyph` op carries its `run`, the tiles the renderer would paste
(`preview.Stamp`), each at a whole-pixel offset from the op's anchor at the
frame's scale, ``(floor(x * scale), floor(y * scale))``.  The tiles live
once each in a `Tiles` store, so moving a text is moving its anchor, and a
reader needs no font, alignment or layout rule.

`rasterise` is the reference reader: it paints JSON ops onto a `Renderer`'s
canvas with plain Pillow calls, and pastes runs, and nothing else.  It is
the contract a browser canvas implements: for every lowered element, its
pixels equal the evaluator's (`tests/test_draw_layers.py`), and the
browser's `ts/app/raster.js` equals it byte for byte
(`tests/test_studio_raster.py`).
"""

from __future__ import annotations

import hashlib
import math
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

from . import barrel
from .evaluator import Evaluator, Stop, part_ops, paste_glyph, series_ops
from .program import (
    AodPick, ArcProgress, ArcSpan, Assign, Bin, Blank, Comment, Const, FillPolygon,
    Continue, Font, For, Glyph, Grown, If, IfAod, IfAwake, IfNotNull, Let, LetAutoScale, LetSlotPick,
    LetText, Lit, LoadFont, Num, Op, Part, Primitive, Return, SeriesDraw, SeriesRebuild,
    SlotIcon, SlotPull, SlotText, SetColor, SetPen, Shifted, Text,
    VisibleGuard, NullGuard, AntiAlias,
)

if TYPE_CHECKING:
    from typing import TypeAlias

    from PIL import Image

    from ..devices import FontMetric
    from ..layout import Placed
    from ..preview import Renderer

#: A number in the JSON: a plain value, or a `Layout` constant plus an offset.
JsonNum: "TypeAlias" = Union[float, dict[str, Any]]

#: Every op `to_json` emits, all of which `raster.js` draws exactly.  A new
#: op joins this list only once the browser draws it too.
BROWSER_OPS = frozenset({
    "color", "pen", "fillPolygon", "arc", "text", "glyph",
    "fillRectangle", "drawRectangle", "fillRoundedRectangle", "drawRoundedRectangle",
    "fillCircle", "drawCircle", "fillEllipse", "drawEllipse", "drawLine",
})


class Tiles:
    """The tiles a frame's runs paste, each stored once: an "L" mask (to be
    tinted) or an RGBA image (pasted through its own alpha)."""

    def __init__(self) -> None:
        self.images: dict[str, "Image.Image"] = {}
        self._ids: dict[tuple[str, int, int, str], str] = {}

    def add(self, image: "Image.Image") -> str:
        key = (image.mode, image.width, image.height,
               hashlib.sha1(image.tobytes()).hexdigest())
        found = self._ids.get(key)
        if found is None:
            found = self._ids[key] = f"t{len(self._ids)}"
            self.images[found] = image
        return found

    def pack(self) -> tuple[bytes, dict[str, list[Any]]]:
        """Every tile as RGBA bytes, one after another, zlib-compressed, and
        their index ``{id: [offset, width, height, kind]}``.  A mask is its
        coverage in alpha over white.  Raw bytes, not a PNG: a browser
        canvas premultiplies alpha, which would lose a translucent RGBA
        tile's colour."""
        from PIL import Image

        out = bytearray()
        index: dict[str, list[Any]] = {}
        for tid, image in self.images.items():
            if image.mode == "L":
                rgba = Image.new("RGBA", image.size, (255, 255, 255, 0))
                rgba.putalpha(image)
                kind = "mask"
            else:
                rgba = image.convert("RGBA")
                kind = "rgba"
            index[tid] = [len(out), image.width, image.height, kind]
            out += rgba.tobytes()
        return zlib.compress(bytes(out), 6), index


@dataclass(frozen=True)
class FontRef:
    """What a JSON font id stands for: a baked sheet (`ResolvedFace.fonts`
    key) or a device face (its metric), and whether it is a `face:` font."""

    baked: str | None
    metric: "FontMetric | None"
    vector: bool = False


def to_json(renderer: "Renderer", placed: "Placed", tiles: Tiles | None = None
            ) -> tuple[list[dict[str, Any]], dict[str, FontRef]]:
    """``placed``'s program for the frame ``renderer`` paints (`--aod` or
    not, its sample readings), as JSON ops and the fonts they name, the
    runs' tiles added to ``tiles``.  The element must lower, and must show
    (`Renderer.shows`)."""
    from . import _context, program

    ops = program(_context(renderer, placed), placed, renderer.read_plan)
    writer = _JsonWriter(renderer, tiles if tiles is not None else Tiles())
    try:
        writer.walk(ops)
    except Stop:
        pass
    return writer.out, writer.fonts


class _JsonWriter:
    def __init__(self, renderer: "Renderer", tiles: Tiles) -> None:
        self.aod = renderer.options.aod
        self.renderer = renderer
        self.eval = Evaluator(renderer)
        self.tiles = tiles
        self.out: list[dict[str, Any]] = []
        self.fonts: dict[str, FontRef] = {}

    def run(self, op: dict[str, Any], draw: Any) -> list[dict[str, Any]]:
        """What ``draw(renderer)`` would paint for ``op``, as tiles placed
        relative to the op's anchor (`anchor_of`)."""
        r = self.renderer
        r.stamps = []
        try:
            draw(r)
            stamps = r.stamps
        finally:
            r.stamps = None
        ax, ay = anchor_of(op, r.scale)
        out: list[dict[str, Any]] = []
        for st in stamps:
            if st.kind == "box":
                out.append({"box": [st.x - ax, st.y - ay, st.size[0], st.size[1]],
                            "rgb": list(st.color)})
            else:
                assert st.image is not None
                out.append({"tile": self.tiles.add(st.image), "x": st.x - ax, "y": st.y - ay})
        return out

    def num(self, n: Num) -> JsonNum:
        """A `Layout` constant, or one moved by a whole amount, stays named;
        anything else the watch computes is folded to its value."""
        if isinstance(n, Const):
            return {"const": n.name, "value": n.value, "add": 0}
        if isinstance(n, Lit):
            return n.value
        if isinstance(n, AodPick):
            return self.num(n.asleep if self.aod and n.asleep is not None else n.awake)
        if isinstance(n, (Shifted, Grown)):
            add = n.by if isinstance(n, Shifted) else n.by * n.times
            base = self.num(n.base)
            if isinstance(base, dict):
                return {**base, "add": base["add"] + add}
            return base + add
        if isinstance(n, Bin) and n.op in ("+", "-") and isinstance(n.a, Const):
            # `Layout.X + x0`: the constant, moved by what the watch adds.
            add = self.eval.num(n.b)
            if isinstance(add, (int, float)):
                return {"const": n.a.name, "value": n.a.value,
                        "add": add if n.op == "+" else -add}
        return float(self.eval.num(n))

    def font(self, font: Font) -> str:
        face = font.asleep if self.aod and font.asleep is not None else font
        ref = FontRef(face.baked, face.metric, face.vector)
        for key, known in self.fonts.items():
            if known == ref:
                return key
        key = f"f{len(self.fonts)}"
        self.fonts[key] = ref
        return key

    def walk(self, ops: "list[Op] | tuple[Op, ...]") -> None:
        for op in ops:
            self.op(op)

    def op(self, op: Op) -> None:
        ev = self.eval
        if isinstance(op, SetColor):
            ev.color = ev.paint(op.color)
            self.out.append({"op": "color", "rgb": list(ev.color)})
        elif isinstance(op, SetPen):
            ev.run([op])
            self.out.append({"op": "pen", "width": self.num(op.width) if op.width else 1})
        elif isinstance(op, Primitive):
            self.out.append({"op": op.name,
                             "args": [self.num(n) for group in op.args for n in group]})
        elif isinstance(op, FillPolygon):
            self.out.append({"op": "fillPolygon", "const": op.const,
                             "points": [list(p) for p in op.points]})
        elif isinstance(op, ArcProgress):
            call = barrel.draw_progress(ev.num(op.start), ev.num(op.sweep), ev.num(op.fraction))
            self.out.append({
                "op": "arc", "cx": self.num(op.cx), "cy": self.num(op.cy),
                "radius": self.num(op.radius), "pen": self.num(op.pen),
                "start": self.num(op.start), "sweep": self.num(op.sweep),
                # The fill fraction this frame's reading gives: a live
                # handle's new start or sweep goes through it again.
                "fraction": float(ev.num(op.fraction)),
                # What `WfbArc.drawProgress` hands `dc.drawArc`.
                "call": list(call) if call is not None else None,
            })
            ev.pen = 1
            self.out.append({"op": "pen", "width": 1})  # the barrel resets it
        elif isinstance(op, Part):
            self.walk(part_ops(op, ev))
        elif isinstance(op, SeriesRebuild):
            ev.run([op])
        elif isinstance(op, SeriesDraw):
            self.walk(series_ops(op, ev))
        elif isinstance(op, (Let, Assign, LetSlotPick, LetAutoScale, VisibleGuard, NullGuard, AntiAlias, Return,
                             SlotPull, SlotIcon, SlotText)):
            ev.run([op])
        elif isinstance(op, If):
            self.walk(op.then if ev.cond(op.cond) else op.otherwise)
        elif isinstance(op, For):
            ev.loop(op, self.walk)
        elif isinstance(op, Continue):
            ev.run([op])
        elif isinstance(op, ArcSpan):
            call = barrel.draw_span(ev.num(op.start), ev.num(op.sweep))
            self.out.append({
                "op": "arc", "cx": self.num(op.cx), "cy": self.num(op.cy),
                "radius": self.num(op.radius), "pen": self.num(op.pen),
                "start": self.num(op.start), "sweep": self.num(op.sweep),
                # What `WfbArc.drawSpan` hands `dc.drawArc`: Garmin degrees.
                "call": list(call) if call is not None else None,
            })
            ev.pen = 1
            self.out.append({"op": "pen", "width": 1})  # the barrel resets it
        elif isinstance(op, Text):
            text = ev.string(op.text)
            if text is None:
                return
            out: dict[str, Any] = {
                "op": "text", "x": self.num(op.x), "y": self.num(op.y), "text": text,
                "font": self.font(op.font), "justify": list(op.justify),
                "align": op.align, "valign": op.valign, "style": op.style,
                "angle": float(ev.num(op.angle)) if op.angle is not None else None,
                "radius": op.radius.value if op.radius is not None else None,
                "direction": op.direction,
                "box": ([op.box.x, op.box.y, op.box.width, op.box.height]
                        if op.box is not None else None),
            }
            fonts = self.fonts
            out["run"] = self.run(out, lambda r: _draw_text(out, fonts, r, ev.color))
            self.out.append(out)
        elif isinstance(op, Glyph):
            glyph = ev.string(op.glyph)
            if glyph is None:
                return
            glyph_op: dict[str, Any] = {
                "op": "glyph", "x": self.num(op.x), "y": self.num(op.y), "text": glyph,
                "font": self.font(op.font), "justify": list(op.justify), "valign": op.valign,
                # The tile's place: the icon's measured box, moved with x/y
                # from where they stand unmoved.
                "box": [op.box.x, op.box.y, op.box.width, op.box.height],
                "origin": list(op.origin),
            }
            fonts = self.fonts
            glyph_op["run"] = self.run(glyph_op,
                                       lambda r: _draw_glyph(glyph_op, fonts, r, ev.color))
            self.out.append(glyph_op)
        elif isinstance(op, LetText):
            ev.run([op])
        elif isinstance(op, IfNotNull):
            if op.present:
                self.walk(op.body)
        elif isinstance(op, IfAod):
            self.walk(op.then if self.aod else op.otherwise)
        elif isinstance(op, IfAwake):
            if not self.aod:
                self.walk(op.body)
        elif isinstance(op, (LoadFont, Comment, Blank)):
            pass
        else:  # pragma: no cover - every Op is handled above
            raise TypeError(f"not an op: {op!r}")


# -- the reference rasteriser -----------------------------------------------------


def _value(n: JsonNum) -> float:
    return float(n["value"] + n["add"]) if isinstance(n, dict) else float(n)


def anchor_of(op: dict[str, Any], scale: int) -> tuple[int, int]:
    """The canvas pixel a `text` or `glyph` op's run is placed from."""
    return math.floor(_value(op["x"]) * scale), math.floor(_value(op["y"]) * scale)


def _draw_glyph(op: dict[str, Any], fonts: dict[str, FontRef], renderer: "Renderer",
                color: tuple[int, int, int]) -> None:
    """A `glyph` op as the evaluator draws it: the run's source."""
    ref = fonts[op["font"]]
    if ref.baked is not None:
        paste_glyph(renderer, ref.baked, op["text"],
                    op["box"][0] + _value(op["x"]) - op["origin"][0],
                    op["box"][1] + _value(op["y"]) - op["origin"][1], color)


def _draw_text(op: dict[str, Any], fonts: dict[str, FontRef], renderer: "Renderer",
               color: tuple[int, int, int]) -> None:
    """A `text` op as the evaluator draws it: the run's source."""
    from ..units import IntBox

    ref = fonts[op["font"]]
    anchor = (int(_value(op["x"])), int(_value(op["y"])))
    align = op["align"] or next(
        (_ALIGN[f] for f in op["justify"] if f in _ALIGN), "center")
    box = IntBox(*op["box"]) if op["box"] is not None else None
    if ref.vector:
        renderer.draw_vector_text(
            op["text"], anchor, align, op["valign"], ref.metric, color, op["style"],
            op["angle"] if op["angle"] is not None else 0.0,
            int(op["radius"]) if op["radius"] is not None else 0,
            op["direction"], box=box)
    else:
        font = renderer.resolved.fonts.get(ref.baked) if ref.baked is not None else None
        renderer.draw_text(font, op["text"], anchor, align, op["valign"], ref.metric,
                           color, box=box)


def paste_run(run: list[dict[str, Any]], anchor: tuple[int, int], tiles: Tiles,
              renderer: "Renderer", color: tuple[int, int, int]) -> None:
    """A run's tiles pasted as Pillow pastes them: a mask tinted ``color``,
    an RGBA image through its own alpha, a box as a 1 px outline."""
    from PIL import Image

    ax, ay = anchor
    for item in run:
        if "box" in item:
            x, y, w, h = item["box"]
            renderer.draw.rectangle([ax + x, ay + y, ax + x + w, ay + y + h],
                                    outline=tuple(item["rgb"]), width=1)
            continue
        image = tiles.images[item["tile"]]
        at = (ax + item["x"], ay + item["y"])
        if image.mode == "L":
            renderer.image.paste(Image.new("RGB", image.size, color), at, image)
        else:
            renderer.image.paste(image, at, image)


_ALIGN = {"TEXT_JUSTIFY_LEFT": "left", "TEXT_JUSTIFY_RIGHT": "right"}


def rasterise(ops: list[dict[str, Any]], tiles: Tiles, renderer: "Renderer") -> None:
    """Paint JSON ops onto ``renderer``'s canvas: `Dc`'s calls as Pillow
    draws them at the preview's scale, and text and icons by pasting their
    runs' tiles."""
    s = renderer.scale
    draw = renderer.draw
    color: tuple[int, int, int] = (255, 255, 255)
    pen = 1
    for op in ops:
        name = op["op"]
        if name == "color":
            color = (op["rgb"][0], op["rgb"][1], op["rgb"][2])
        elif name == "pen":
            pen = int(_value(op["width"]))
        elif name == "fillPolygon":
            if len(op["points"]) >= 3:
                draw.polygon([(x * s, y * s) for x, y in op["points"]], fill=color)
        elif name == "arc":
            radius = _value(op["radius"])
            if op["call"] is None or radius <= 0:
                continue
            cx, cy, rr = _value(op["cx"]) * s, _value(op["cy"]) * s, radius * s
            start, end, clockwise = op["call"]
            draw.arc([cx - rr, cy - rr, cx + rr, cy + rr],
                     *barrel.pillow_arc((start, end, clockwise)), fill=color,
                     width=max(1, int(_value(op["pen"])) * s))
        elif name in ("glyph", "text"):
            paste_run(op["run"], anchor_of(op, s), tiles, renderer, color)
        else:
            v = [_value(n) for n in op["args"]]
            width = max(1, pen * s)
            fill = name.startswith("fill")
            shape = name[4:]
            if shape in ("Rectangle", "RoundedRectangle"):
                x, y, w, h = v[:4]
                if w <= 0 or h <= 0:
                    continue  # `Dc` draws nothing
                rect = [x * s, y * s, (x + w) * s - 1, (y + h) * s - 1]
                if shape == "Rectangle":
                    if fill:
                        draw.rectangle(rect, fill=color)
                    else:
                        draw.rectangle(rect, outline=color, width=width)
                elif fill:
                    draw.rounded_rectangle(rect, radius=v[4] * s, fill=color)
                else:
                    draw.rounded_rectangle(rect, radius=v[4] * s, outline=color, width=width)
            elif shape in ("Circle", "Ellipse"):
                cx, cy = v[0], v[1]
                rx, ry = (v[2], v[2]) if shape == "Circle" else (v[2], v[3])
                ellipse = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
                if fill:
                    draw.ellipse(ellipse, fill=color)
                else:
                    draw.ellipse(ellipse, outline=color, width=width)
            elif name == "drawLine":
                draw.line([v[0] * s, v[1] * s, v[2] * s, v[3] * s], fill=color, width=width)
            else:
                raise ValueError(f"no reference rasterisation for {name!r}")
