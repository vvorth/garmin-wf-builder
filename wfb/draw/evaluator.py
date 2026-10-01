"""Backend 2: a draw program painted on the host.

It emulates the `Dc` calls a program makes on the preview's own
`Renderer`: its `ImageDraw` at the preview's upscale, its glyph sources
(`Renderer.draw_text`, `draw_vector_text`) and its sample readings.  A
barrel call is computed with its transcription (`wfb.draw.barrel`), so an
arc covers the degrees the watch's `drawArc` covers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .. import expr, formatting
from ..catalog import Type
from . import barrel
from .program import (
    ArcSpan, Blank, Comment, Concat, Const, FillPolygon, Grown, IfAod, IfNotNull, LetText, Lit,
    LoadFont, Num, Op, Primitive, Reading, SetColor, SetPen, Shifted, Str, StrLit, Text,
)

if TYPE_CHECKING:
    from ..preview import Renderer

RGB = tuple[int, int, int]

_JUSTIFY_ALIGN = {"TEXT_JUSTIFY_LEFT": "left", "TEXT_JUSTIFY_RIGHT": "right"}


def num_value(n: Num) -> float:
    if isinstance(n, (Const, Lit)):
        return n.value
    if isinstance(n, Shifted):
        return num_value(n.base) + n.by
    assert isinstance(n, Grown)
    return num_value(n.base) + n.by * n.times


def str_value(s: Str, values: dict[str, object], env: dict[str, str | None]) -> str | None:
    """``s`` at the sample readings, or `None` when a reading in it is
    absent."""
    if isinstance(s, StrLit):
        return s.text
    if isinstance(s, Reading):
        value_type = s.value.value.type
        if value_type in (Type.TIME, Type.DATE):
            return formatting.render(s.spec, None, value_type, values)
        reading = expr.evaluate(s.value.ast, values) if s.value.ast else None
        if reading is None:
            return None
        unit = (str(expr.evaluate(s.unit.ast, values))
                if s.unit is not None and s.unit.ast is not None else None)
        return formatting.render(s.spec, reading, value_type, values, unit_text=unit)
    if isinstance(s, Concat):
        parts = [str_value(part, values, env) for part in s.parts]
        if any(part is None for part in parts):
            return None
        return "".join(part for part in parts if part is not None)
    return env[s.name]


class Evaluator:
    """Paints one element's program into a `Renderer`, keeping the `Dc`
    state (colour, pen width) and the program's locals between ops."""

    def __init__(self, renderer: "Renderer") -> None:
        self.renderer = renderer
        self.color: RGB = (255, 255, 255)
        self.pen = 1
        self.locals: dict[str, str | None] = {}

    def run(self, ops: Iterable[Op]) -> None:
        for op in ops:
            self._run(op)

    def _run(self, op: Op) -> None:
        r = self.renderer
        if isinstance(op, SetColor):
            self.color = r.color(op.color.expr)
        elif isinstance(op, SetPen):
            self.pen = int(num_value(op.width)) if op.width is not None else 1
        elif isinstance(op, Primitive):
            self._primitive(op)
        elif isinstance(op, FillPolygon):
            if len(op.points) >= 3:
                s = r.scale
                r.draw.polygon([(x * s, y * s) for x, y in op.points], fill=self.color)
        elif isinstance(op, ArcSpan):
            self._arc(op)
        elif isinstance(op, Text):
            self._text(op)
        elif isinstance(op, LetText):
            value = str_value(op.value, r.values, self.locals)
            self.locals[op.name] = (value if value is not None
                                    else str_value(op.initial, r.values, self.locals))
        elif isinstance(op, IfNotNull):
            # A loaded font is never null on the host.
            self.run(op.body)
        elif isinstance(op, IfAod):
            self.run(op.then if r.options.aod else op.otherwise)
        elif isinstance(op, (LoadFont, Comment, Blank)):
            pass
        else:  # pragma: no cover - every Op is handled above
            raise TypeError(f"not an op: {op!r}")

    def _primitive(self, op: Primitive) -> None:
        r = self.renderer
        s = r.scale
        v = [num_value(n) for group in op.args for n in group]
        fill = op.name.startswith("fill")
        shape = op.name[4:]
        width = max(1, self.pen * s)
        draw = r.draw
        if shape in ("Rectangle", "RoundedRectangle"):
            x, y, w, h = v[:4]
            box = [x * s, y * s, (x + w) * s - 1, (y + h) * s - 1]
            if shape == "Rectangle":
                if fill:
                    draw.rectangle(box, fill=self.color)
                else:
                    draw.rectangle(box, outline=self.color, width=width)
            elif fill:
                draw.rounded_rectangle(box, radius=v[4] * s, fill=self.color)
            else:
                draw.rounded_rectangle(box, radius=v[4] * s, outline=self.color, width=width)
        elif shape in ("Circle", "Ellipse"):
            cx, cy = v[0], v[1]
            rx, ry = (v[2], v[2]) if shape == "Circle" else (v[2], v[3])
            box = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
            if fill:
                draw.ellipse(box, fill=self.color)
            else:
                draw.ellipse(box, outline=self.color, width=width)
        elif op.name == "drawLine":
            draw.line([v[0] * s, v[1] * s, v[2] * s, v[3] * s], fill=self.color, width=width)
        else:
            raise ValueError(f"no host emulation for dc.{op.name}")

    def _arc(self, op: ArcSpan) -> None:
        r = self.renderer
        radius = num_value(op.radius)
        call = barrel.draw_span(num_value(op.start), num_value(op.sweep))
        if radius <= 0 or call is None:
            return
        s = r.scale
        cx, cy, rr = num_value(op.cx) * s, num_value(op.cy) * s, radius * s
        r.draw.arc([cx - rr, cy - rr, cx + rr, cy + rr], *barrel.pillow_arc(call),
                   fill=self.color, width=max(1, int(num_value(op.pen)) * s))

    def _text(self, op: Text) -> None:
        r = self.renderer
        text = str_value(op.text, r.values, self.locals)
        if text is None:
            return
        anchor = (int(num_value(op.x)), int(num_value(op.y)))
        align = next((_JUSTIFY_ALIGN[f] for f in op.justify if f in _JUSTIFY_ALIGN), "center")
        if op.font.vector:
            r.draw_vector_text(
                text, anchor, align, op.valign, op.font.metric, self.color, op.style,
                op.angle.value if op.angle is not None else 0.0,
                int(op.radius.value) if op.radius is not None else 0,
                op.direction, box=op.box)
            return
        font = r.resolved.fonts.get(op.font.baked) if op.font.baked is not None else None
        r.draw_text(font, text, anchor, align, op.valign,
                    None if font is not None else op.font.metric, self.color, box=op.box)


def evaluate(ops: Iterable[Op], renderer: "Renderer") -> None:
    """Paint ``ops`` into ``renderer``'s current image."""
    Evaluator(renderer).run(ops)
