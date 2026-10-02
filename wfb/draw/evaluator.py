"""Backend 2: a draw program painted on the host.

It emulates the `Dc` calls a program makes on the preview's own
`Renderer`: its `ImageDraw` at the preview's upscale, its glyph sources
(`Renderer.draw_text`, `draw_vector_text`) and its sample readings.  A
barrel call is computed with its transcription (`wfb.draw.barrel`), so an
arc covers the degrees the watch's `drawArc` covers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .. import expr, formatting, icons
from ..catalog import Type
from ..ir import disc_perimeter_offsets
from . import barrel
from .program import (
    AodDimmed, AodPaint, AodPart, AodPick, AodRestyled, AodStr, ArcProgress, ArcSpan, Assign, Bin,
    Blank, Call, Cmp, Color, Comment, Concat, Cond, Const, Conv, Disagreement, FillPolygon,
    FloatLit, For, Glyph, Grown, IconChoice, If, IfAod, IfAwake, IfNotNull, Let, LetAutoScale,
    LetSlotPick, LetText, Lit, LoadFont, LocalsSet, NotPulsing, Num, NumLocal, NumPick, Op, Paint,
    PaintPick, Paren, Part, Present, Primitive, Read, Reading, SetColor, SetPen, Shifted, Str,
    StrLit, Text, WrapperGuard,
)

if TYPE_CHECKING:
    from ..ir.model import Expression
    from ..preview import Renderer

RGB = tuple[int, int, int]

_JUSTIFY_ALIGN = {"TEXT_JUSTIFY_LEFT": "left", "TEXT_JUSTIFY_RIGHT": "right"}


@dataclass(frozen=True)
class Pulled:
    """The host's stand-in for a pulled `Complications.Complication`: there
    is always one, and its `value` is the sample reading, absent or not."""

    value: object
    unit: object = None


class Stop(Exception):
    """A `WrapperGuard` found a probe absent: the element draws nothing
    more."""


#: How tightly each operator a `Bin` prints binds, as Monkey C parses it.
_PRECEDENCE = {"*": 2, "/": 2, "%": 2, "+": 1, "-": 1}


def read_value(e: "Expression", values: Mapping[str, object]) -> Any:
    """A bound expression at the sample readings: its number (or other
    value), or `None` when it is absent."""
    if e.constant is not None:
        return e.constant
    if e.ast is None:
        return None
    return expr.evaluate(e.ast, dict(values))


def _arith(a: Any, op: str, b: Any) -> Any:
    """One Monkey C operator on two numbers: two `Number`s stay whole, and
    `/` and `%` on them truncate toward zero."""
    if a is None or b is None:
        return None
    whole = isinstance(a, int) and isinstance(b, int)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if whole:
            quotient = abs(a) // abs(b)
            return quotient if (a < 0) == (b < 0) else -quotient
        return float(a) / float(b)
    if whole:
        return barrel.mc_mod(a, b)
    return float(a) % float(b)  # pragma: no cover - no program takes a Float's %


def num_value(n: Num, aod: bool = False, env: Mapping[str, Any] | None = None,
              values: Mapping[str, object] | None = None) -> Any:
    """``n`` on this device, in the always-on frame when ``aod``, with the
    program's locals ``env`` and the sample readings ``values``: a number,
    or `None` when a reading in it is absent."""
    env = {} if env is None else env
    values = {} if values is None else values

    def value(m: Num) -> Any:
        return num_value(m, aod, env, values)

    if isinstance(n, (Const, Lit)):
        return n.value
    if isinstance(n, FloatLit):
        return float(n.value)
    if isinstance(n, NumLocal):
        return env[n.name]
    if isinstance(n, Read):
        found = read_value(n.expr, values)
        return None if found is None else expr.as_number(found)
    if isinstance(n, AodPick):
        return value(n.asleep if aod and n.asleep is not None else n.awake)
    if isinstance(n, Paren):
        return value(n.inner)
    if isinstance(n, Call):
        args = [value(arg) for arg in n.args]
        return None if any(arg is None for arg in args) else barrel.CALLS[n.fn](*args)
    if isinstance(n, Conv):
        inner = value(n.inner)
        if inner is None:
            return None
        return barrel.to_number(inner) if n.method == "toNumber" else float(inner)
    if isinstance(n, NumPick):
        return value(n.then if cond_value(n.cond, aod, env, values) else n.otherwise)
    # A chain of infix operators, printed bare: evaluate it the way Monkey C
    # parses the printed text, not the way the tree nests.
    terms: list[Any] = []
    ops: list[str] = []
    _flatten(n, terms, ops, value)
    for level in (2, 1):
        i = 0
        while i < len(ops):
            if _PRECEDENCE[ops[i]] == level:
                terms[i:i + 2] = [_arith(terms[i], ops[i], terms[i + 1])]
                del ops[i]
            else:
                i += 1
    return terms[0]


def _flatten(n: Num, terms: list[Any], ops: list[str], value: Any) -> None:
    """``n``'s printed infix chain as its terms and operators: a `Bin`, and
    the ``base + 2``/``base - 1`` a `Shifted` or `Grown` prints."""
    if isinstance(n, Bin):
        _flatten(n.a, terms, ops, value)
        ops.append(n.op)
        _flatten(n.b, terms, ops, value)
    elif isinstance(n, Shifted) and n.by != 0:
        _flatten(n.base, terms, ops, value)
        ops.append("+" if n.by > 0 else "-")
        terms.append(abs(n.by))
    elif isinstance(n, Grown):
        _flatten(n.base, terms, ops, value)
        amount = n.by * n.times
        ops.append("+" if amount >= 0 else "-")
        terms.append(abs(amount))
    elif isinstance(n, Shifted):
        _flatten(n.base, terms, ops, value)
    else:
        terms.append(value(n))


def cond_value(c: Cond, aod: bool = False, env: Mapping[str, Any] | None = None,
               values: Mapping[str, object] | None = None) -> bool:
    """Whether ``c`` holds on the host."""
    env = {} if env is None else env
    values = {} if values is None else values
    if isinstance(c, Present):
        return all(read_value(probe, values) is not None for probe in c.probes)
    if isinstance(c, LocalsSet):
        return all(env.get(name) is not None for name in c.names)
    if isinstance(c, Cmp):
        a, b = num_value(c.a, aod, env, values), num_value(c.b, aod, env, values)
        if c.op == "==":
            return bool(a == b)
        if c.op == "!=":
            return bool(a != b)
        if a is None or b is None:
            return False
        return bool({"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[c.op])
    assert isinstance(c, NotPulsing)
    return True


def str_value(s: Str, values: dict[str, object], env: Mapping[str, Any],
              aod: bool = False) -> str | None:
    """``s`` at the sample readings, in the always-on frame when ``aod``,
    or `None` when a reading in it is absent."""
    if isinstance(s, AodStr):
        return str_value(s.asleep if aod else s.awake, values, env, aod)
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
        parts = [str_value(part, values, env, aod) for part in s.parts]
        if any(part is None for part in parts):
            return None
        return "".join(part for part in parts if part is not None)
    if isinstance(s, IconChoice):
        reading = expr.evaluate(s.value.ast, values) if s.value.ast else None
        return icons.CATALOG[icons.choose_weather_icon(reading)].codepoint
    found = env[s.name]
    assert found is None or isinstance(found, str), s.name
    return found


class Evaluator:
    """Paints one element's program into a `Renderer`, keeping the `Dc`
    state (colour, pen width) and the program's locals between ops."""

    def __init__(self, renderer: "Renderer", ring_color: RGB | None = None) -> None:
        self.renderer = renderer
        #: What `RingColor` paints: an outlined group's colour, for a ring
        #: pass.
        self.ring_color = ring_color
        self.color: RGB = (255, 255, 255)
        self.pen = 1
        #: The program's locals: strings (`LetText`) and numbers (`Let`,
        #: `For`), `None` while absent.
        self.locals: dict[str, Any] = {}

    def num(self, n: Num) -> Any:
        r = self.renderer
        return num_value(n, r.options.aod, self.locals, r.values)

    def cond(self, c: Cond) -> bool:
        r = self.renderer
        return cond_value(c, r.options.aod, self.locals, r.values)

    def string(self, s: Str) -> str | None:
        r = self.renderer
        return str_value(s, r.values, self.locals, r.options.aod)

    def paint(self, c: Paint) -> RGB:
        r = self.renderer
        if isinstance(c, Color):
            return r.color(c.expr)
        if isinstance(c, AodRestyled):
            return r.aod_color(c.element, c.key, getattr(c.element, c.key))
        if isinstance(c, AodDimmed):
            return r.aod_dimmed(c.element, c.expr)
        if isinstance(c, AodPaint):
            return self.paint(c.asleep if r.options.aod else c.awake)
        if isinstance(c, AodPart):
            return r.aod_color(c.element, "color", c.expr)
        if isinstance(c, PaintPick):
            return self.paint(c.then if self.cond(c.cond) else c.otherwise)
        if self.ring_color is None:
            raise ValueError("a ring pass painted without its group's colour")
        return self.ring_color

    def run(self, ops: Iterable[Op]) -> None:
        for op in ops:
            self._run(op)

    def run_program(self, ops: Iterable[Op]) -> None:
        """`run` a whole element's program, which a `WrapperGuard` may end
        early."""
        try:
            self.run(ops)
        except Stop:
            pass

    def _run(self, op: Op) -> None:
        r = self.renderer
        if isinstance(op, SetColor):
            self.color = self.paint(op.color)
        elif isinstance(op, SetPen):
            self.pen = int(self.num(op.width)) if op.width is not None else 1
        elif isinstance(op, Primitive):
            self._primitive(op)
        elif isinstance(op, FillPolygon):
            if len(op.points) >= 3:
                s = r.scale
                r.draw.polygon([(x * s, y * s) for x, y in op.points], fill=self.color)
        elif isinstance(op, ArcSpan):
            self._arc(op)
        elif isinstance(op, ArcProgress):
            self._progress(op)
        elif isinstance(op, Part):
            self.run(part_ops(op, self))
        elif isinstance(op, Let | Assign):
            self.locals[op.name] = self.num(op.value)
        elif isinstance(op, If):
            self.run(op.then if self.cond(op.cond) else op.otherwise)
        elif isinstance(op, For):
            for i in range(int(self.num(op.bound))):
                self.locals[op.var] = i
                self.run(op.body)
        elif isinstance(op, LetSlotPick):
            self.locals["pulled"] = Pulled(op.sample)
            self.locals["scale"] = op.scale
        elif isinstance(op, LetAutoScale):
            self.locals["scale"] = auto_scale(op, r.values)
        elif isinstance(op, WrapperGuard):
            if any(read_value(probe, r.values) is None for probe in op.probes):
                raise Stop
        elif isinstance(op, Text):
            self._text(op)
        elif isinstance(op, Glyph):
            self._glyph(op)
        elif isinstance(op, LetText):
            value = self.string(op.value)
            self.locals[op.name] = value if value is not None else self.string(op.initial)
        elif isinstance(op, IfNotNull):
            # A loaded font is never null on the host.
            self.run(op.body)
        elif isinstance(op, IfAod):
            self.run(op.then if r.options.aod else op.otherwise)
        elif isinstance(op, IfAwake):
            if not r.options.aod:
                self.run(op.body)
        elif isinstance(op, Disagreement):
            self.run(op.preview)
        elif isinstance(op, (LoadFont, Comment, Blank)):
            pass
        else:  # pragma: no cover - every Op is handled above
            raise TypeError(f"not an op: {op!r}")

    def _primitive(self, op: Primitive) -> None:
        r = self.renderer
        s = r.scale
        v = [self.num(n) for group in op.args for n in group]
        fill = op.name.startswith("fill")
        shape = op.name[4:]
        width = max(1, self.pen * s)
        draw = r.draw
        if shape in ("Rectangle", "RoundedRectangle"):
            x, y, w, h = v[:4]
            if w <= 0 or h <= 0:
                return  # `Dc` draws nothing
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
        radius = self.num(op.radius)
        call = barrel.draw_span(self.num(op.start), self.num(op.sweep))
        if radius <= 0 or call is None:
            return
        s = r.scale
        cx, cy, rr = self.num(op.cx) * s, self.num(op.cy) * s, radius * s
        r.draw.arc([cx - rr, cy - rr, cx + rr, cy + rr], *barrel.pillow_arc(call),
                   fill=self.color, width=max(1, int(self.num(op.pen)) * s))

    def _progress(self, op: ArcProgress) -> None:
        """`WfbArc.drawProgress`: its `drawSpan` call, or none."""
        r = self.renderer
        radius = self.num(op.radius)
        call = barrel.draw_progress(self.num(op.start), self.num(op.sweep),
                                    self.num(op.fraction))
        if radius <= 0 or call is None:
            return
        s = r.scale
        cx, cy, rr = self.num(op.cx) * s, self.num(op.cy) * s, radius * s
        r.draw.arc([cx - rr, cy - rr, cx + rr, cy + rr], *barrel.pillow_arc(call),
                   fill=self.color, width=max(1, int(self.num(op.pen)) * s))

    def _text(self, op: Text) -> None:
        r = self.renderer
        text = self.string(op.text)
        if text is None:
            return
        anchor = (int(self.num(op.x)), int(self.num(op.y)))
        align = op.align or next(
            (_JUSTIFY_ALIGN[f] for f in op.justify if f in _JUSTIFY_ALIGN), "center")
        face = op.font.asleep if r.options.aod and op.font.asleep is not None else op.font
        if face.vector:
            r.draw_vector_text(
                text, anchor, align, op.valign, face.metric, self.color, op.style,
                op.angle.value if op.angle is not None else 0.0,
                int(op.radius.value) if op.radius is not None else 0,
                op.direction, box=op.box)
            return
        font = r.resolved.fonts.get(face.baked) if face.baked is not None else None
        r.draw_text(font, text, anchor, align, op.valign, face.metric, self.color, box=op.box)


    def _glyph(self, op: Glyph) -> None:
        r = self.renderer
        text = self.string(op.glyph)
        if text is None or op.font.baked is None:
            return
        paste_glyph(r, op.font.baked, text, op.box.x + self.num(op.x) - op.origin[0],
                    op.box.y + self.num(op.y) - op.origin[1], self.color)


def paste_glyph(renderer: "Renderer", font_key: str, char: str, x: float, y: float,
                color: RGB) -> None:
    """``char``'s tile from the baked sheet ``font_key``, its box's top-left
    at device ``(x, y)``; nothing when the font failed to bake or lacks the
    glyph."""
    from ..preview import baked_glyph

    font = renderer.resolved.fonts.get(font_key)
    glyph = baked_glyph(font, char)
    if glyph is None or font is None or font.sheet is None:
        return
    s = renderer.scale
    renderer.paste_glyph(font.sheet, glyph, x * s, y * s, color)


def part_ops(op: Part, ev: Evaluator) -> list[Op]:
    """What one `Part` call draws, as plain `Dc` ops over device numbers:
    the barrel's own transform (`WfbGeom`, `WfbRing`, `WfbRingWide`) of the
    part's vertices, at the current copy's ``cx``/``cy``/``sin``/``cos`` or
    ``ox``/``oy``.  Coordinates stay fractional, as the barrel hands them to
    `Dc`."""
    part = op.part
    env = ev.locals
    if op.radial:
        cx, cy, sin, cos = env["cx"], env["cy"], env["sin"], env["cos"]

        def at(x: float, y: float) -> tuple[float, float]:
            return cx + (x * cos - y * sin), cy + (x * sin + y * cos)
    else:
        ox, oy = env["ox"], env["oy"]

        def at(x: float, y: float) -> tuple[float, float]:
            return ox + x, oy + y

    stroked = part.shape == "line" or (part.shape == "circle" and not part.filled)
    offsets = [(0, 0)] if op.ring is None else disc_perimeter_offsets(op.ring)
    body: list[Op] = []
    if part.shape == "polygon":
        points = [at(x, y) for x, y in part.points]
        body = [FillPolygon(f"{op.prefix}_POINTS",
                            tuple((x + dx, y + dy) for x, y in points))
                for dx, dy in offsets]
    elif part.shape == "line":
        (x1, y1), (x2, y2) = at(part.x1, part.y1), at(part.x2, part.y2)
        body = [Primitive("drawLine", ((Lit(x1 + dx), Lit(y1 + dy), Lit(x2 + dx), Lit(y2 + dy)),))
                for dx, dy in offsets]
    else:
        x, y = at(part.x, part.y)
        if part.filled and op.ring is not None and op.stamp:
            body = [Primitive("fillCircle", ((Lit(x + dx), Lit(y + dy), Lit(part.radius)),))
                    for dx, dy in offsets]
        elif part.filled:
            # A filled circle's ring is itself grown by the ring's width.
            grow = op.ring or 0
            body = [Primitive("fillCircle", ((Lit(x), Lit(y), Lit(part.radius + grow)),))]
        else:
            body = [Primitive("drawCircle", ((Lit(x + dx), Lit(y + dy), Lit(part.radius)),))
                    for dx, dy in offsets]
    if stroked and op.set_pen:
        return [SetPen(op.pen), *body, SetPen(None)]
    return body


def auto_scale(op: LetAutoScale, values: Mapping[str, object]) -> tuple[float, float] | None:
    """`max: auto`'s scale on the host: the type's own for the preview's
    sample wearer, or `None` when it has none there.  The complication
    itself is always there on the host, so a sample reading that is absent
    still has a scale, and follows `absent:`."""
    from .. import complications
    from ..preview import (
        SAMPLE_GOALS, SAMPLE_HEART_RATE_ZONES, SAMPLE_WEARER_AGE, SAMPLE_WEARER_SEX,
    )

    value = read_value(op.value, values)
    return complications.scale_for(
        op.type_name, goals=SAMPLE_GOALS, heart_rate_zones=SAMPLE_HEART_RATE_ZONES,
        sex=SAMPLE_WEARER_SEX, age=SAMPLE_WEARER_AGE, value=value)


def evaluate(ops: Iterable[Op], renderer: "Renderer") -> None:
    """Paint ``ops`` into ``renderer``'s current image."""
    Evaluator(renderer).run_program(ops)
