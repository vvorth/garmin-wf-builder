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

`rasterise` is the reference reader: it paints JSON ops onto a `Renderer`'s
canvas with plain Pillow calls and the renderer's glyph placement, and
nothing else.  It is the contract a browser canvas implements: for every
lowered element, its pixels equal the evaluator's (`tests/test_draw_layers.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

from . import barrel
from .evaluator import Evaluator
from .program import (
    AodPick, ArcSpan, Blank, Comment, Const, Disagreement, FillPolygon, Font, IfAod,
    IfAwake, IfNotNull, LetText, Lit, LoadFont, Num, Op, Primitive, SetColor, SetPen, Shifted,
    Text,
)

if TYPE_CHECKING:
    from typing import TypeAlias

    from ..devices import FontMetric
    from ..layout import Placed
    from ..preview import Renderer

#: A number in the JSON: a plain value, or a `Layout` constant plus an offset.
JsonNum: "TypeAlias" = Union[float, dict[str, Any]]


@dataclass(frozen=True)
class FontRef:
    """What a JSON font id stands for: a baked sheet (`ResolvedFace.fonts`
    key) or a device face (its metric), and whether it is a `face:` font."""

    baked: str | None
    metric: "FontMetric | None"
    vector: bool = False


def to_json(renderer: "Renderer", placed: "Placed") -> tuple[list[dict[str, Any]],
                                                            dict[str, FontRef]]:
    """``placed``'s program for the frame ``renderer`` paints (`--aod` or
    not, its sample readings), as JSON ops and the fonts they name.  The
    element must lower, and must show (`Renderer.shows`)."""
    from . import _context, lowered

    ops = lowered(_context(renderer, placed), placed)
    if ops is None:
        raise ValueError(f"{placed.id}: its kind does not lower")
    writer = _JsonWriter(renderer)
    writer.walk(ops)
    return writer.out, writer.fonts


class _JsonWriter:
    def __init__(self, renderer: "Renderer") -> None:
        self.aod = renderer.options.aod
        self.eval = Evaluator(renderer)
        self.out: list[dict[str, Any]] = []
        self.fonts: dict[str, FontRef] = {}

    def num(self, n: Num) -> JsonNum:
        if isinstance(n, Const):
            return {"const": n.name, "value": n.value, "add": 0}
        if isinstance(n, Lit):
            return n.value
        if isinstance(n, AodPick):
            return self.num(n.asleep if self.aod and n.asleep is not None else n.awake)
        add = n.by if isinstance(n, Shifted) else n.by * n.times
        base = self.num(n.base)
        if isinstance(base, dict):
            return {**base, "add": base["add"] + add}
        return base + add

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
            self.out.append({"op": "pen", "width": self.num(op.width) if op.width else 1})
        elif isinstance(op, Primitive):
            self.out.append({"op": op.name,
                             "args": [self.num(n) for group in op.args for n in group]})
        elif isinstance(op, FillPolygon):
            self.out.append({"op": "fillPolygon", "const": op.const,
                             "points": [list(p) for p in op.points]})
        elif isinstance(op, ArcSpan):
            call = barrel.draw_span(ev.num(op.start), ev.num(op.sweep))
            self.out.append({
                "op": "arc", "cx": self.num(op.cx), "cy": self.num(op.cy),
                "radius": self.num(op.radius), "pen": self.num(op.pen),
                "start": self.num(op.start), "sweep": self.num(op.sweep),
                # What `WfbArc.drawSpan` hands `dc.drawArc`: Garmin degrees.
                "call": list(call) if call is not None else None,
            })
        elif isinstance(op, Text):
            text = ev.string(op.text)
            if text is None:
                return
            self.out.append({
                "op": "text", "x": self.num(op.x), "y": self.num(op.y), "text": text,
                "font": self.font(op.font), "justify": list(op.justify),
                "align": op.align, "valign": op.valign, "style": op.style,
                "angle": op.angle.value if op.angle is not None else None,
                "radius": op.radius.value if op.radius is not None else None,
                "direction": op.direction,
                "box": ([op.box.x, op.box.y, op.box.width, op.box.height]
                        if op.box is not None else None),
            })
        elif isinstance(op, LetText):
            ev.run([op])
        elif isinstance(op, IfNotNull):
            self.walk(op.body)
        elif isinstance(op, IfAod):
            self.walk(op.then if self.aod else op.otherwise)
        elif isinstance(op, IfAwake):
            if not self.aod:
                self.walk(op.body)
        elif isinstance(op, Disagreement):
            self.walk(op.preview)
        elif isinstance(op, (LoadFont, Comment, Blank)):
            pass
        else:  # pragma: no cover - every Op is handled above
            raise TypeError(f"not an op: {op!r}")


# -- the reference rasteriser -----------------------------------------------------


def _value(n: JsonNum) -> float:
    return float(n["value"] + n["add"]) if isinstance(n, dict) else float(n)


_ALIGN = {"TEXT_JUSTIFY_LEFT": "left", "TEXT_JUSTIFY_RIGHT": "right"}


def rasterise(ops: list[dict[str, Any]], fonts: dict[str, FontRef],
              renderer: "Renderer") -> None:
    """Paint JSON ops onto ``renderer``'s canvas: `Dc`'s calls as Pillow
    draws them at the preview's scale, and text through the renderer's own
    glyph placement."""
    from ..units import IntBox

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
        elif name == "text":
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
        else:
            v = [_value(n) for n in op["args"]]
            width = max(1, pen * s)
            fill = name.startswith("fill")
            shape = name[4:]
            if shape in ("Rectangle", "RoundedRectangle"):
                x, y, w, h = v[:4]
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
