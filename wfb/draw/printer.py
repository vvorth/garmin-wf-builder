"""Backend 1: a draw program as the Monkey C body of `draw<Id>`.

It writes through the emitter's own `Writer` (`call`, `block`, `blank`) and
its spelling helpers (`shifted`, `plus`, `glyph_y_expr`,
`radial_radius_expr`, `mc_color`), so a ported kind prints exactly what its
hand-written `emit_draw` printed.
"""

from __future__ import annotations

from collections.abc import Iterable

from .. import formatting
from ..emit.monkeyc import shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, glyph_y_expr, mc_color, plus
from ..emit.writer import Writer
from ..ir import local_name
from .program import (
    AodDimmed, AodPaint, AodPick, AodRestyled, AodStr, ArcSpan, Blank, Color, Comment, Concat,
    Const, Disagreement, FillPolygon, Glyph, IconChoice, IfAod, IfAwake, IfNotNull, LetText, Lit,
    LoadFont, Num, Op, Paint, Primitive, Reading, SetColor, SetPen, Shifted, Str, StrLit, Text,
)


def num_code(n: Num, aod: AodStyle = NO_AOD) -> str:
    if isinstance(n, Const):
        return f"Layout.{n.name}"
    if isinstance(n, Lit):
        return str(int(n.value)) if float(n.value).is_integer() else repr(n.value)
    if isinstance(n, Shifted):
        return shapes.shifted(num_code(n.base, aod), n.by)
    if isinstance(n, AodPick):
        asleep = num_code(n.asleep, aod) if n.asleep is not None else None
        return aod.value(asleep, num_code(n.awake, aod))
    return plus(num_code(n.base, aod), str(n.by), n.times)


def str_code(s: Str, aod: AodStyle = NO_AOD) -> str:
    if isinstance(s, AodStr):
        return aod.value(str_code(s.asleep, aod), str_code(s.awake, aod))
    if isinstance(s, StrLit):
        return f'"{s.text}"'
    if isinstance(s, Reading):
        return formatting.emit(s.spec, s.value.code, s.value.value.type,
                               unit_code=s.unit.code if s.unit is not None else None)
    if isinstance(s, Concat):
        return " + ".join(str_code(part, aod) for part in s.parts)
    if isinstance(s, IconChoice):
        return f"IconGlyphs.glyph(WfbWeather.chooseIcon({local_name(s.value.sources[0])}))"
    return s.name


def color_code(c: Paint, aod: AodStyle = NO_AOD) -> str:
    if isinstance(c, Color):
        return mc_color(c.expr)
    if isinstance(c, AodRestyled):
        return aod.color(c.element, c.key)
    if isinstance(c, AodDimmed):
        return aod.dimmed(c.element, c.expr)
    if isinstance(c, AodPaint):
        return aod.value(color_code(c.asleep, aod), color_code(c.awake, aod))
    return "ringColor"


def print_ops(w: Writer, ops: Iterable[Op], aod: AodStyle = NO_AOD) -> None:
    """Write ``ops`` into ``w``, in order, spelling every always-on choice
    the way this build's ``aod`` does (none at all in an all-MIP build)."""
    for op in ops:
        _print(w, op, aod)


def _print(w: Writer, op: Op, aod: AodStyle) -> None:
    def n(value: Num) -> str:
        return num_code(value, aod)

    if isinstance(op, SetColor):
        w.line(f"dc.setColor({color_code(op.color, aod)}, Graphics.COLOR_TRANSPARENT);")
    elif isinstance(op, SetPen):
        w.line(f"dc.setPenWidth({n(op.width) if op.width is not None else '1'});")
    elif isinstance(op, Primitive):
        w.call(f"dc.{op.name}", [", ".join(n(v) for v in group) for group in op.args])
    elif isinstance(op, FillPolygon):
        w.line(f"dc.fillPolygon(Layout.{op.const});")
    elif isinstance(op, ArcSpan):
        w.call("WfbArc.drawSpan", [
            f"dc, {n(op.cx)}, {n(op.cy)}, {n(op.radius)}",
            f"{n(op.pen)}, {n(op.start)}, {n(op.sweep)}",
        ])
    elif isinstance(op, LoadFont):
        w.line(f"var {op.local} = {op.source};")
        if op.on_null == "return":
            with w.block(f"if ({op.local} == null)"):
                w.line(f"return;  // {op.note}")
    elif isinstance(op, Text):
        _print_text(w, op, aod)
    elif isinstance(op, Glyph):
        _print_upright(w, op.x, op.y, op.font.code, op.glyph, op.justify, op.valign, aod)
    elif isinstance(op, LetText):
        w.line(f"var {op.name} = {str_code(op.initial, aod)};")
        available = " && ".join(f"{guard} != null" for guard in op.guards)
        with w.block(f"if ({available})"):
            w.line(f"{op.name} = {str_code(op.value, aod)};")
    elif isinstance(op, IfNotNull):
        with w.block(f"if ({op.local} != null)"):
            print_ops(w, op.body, aod)
    elif isinstance(op, IfAod):
        with w.block("if (_aod)"):
            print_ops(w, op.then, aod)
        if op.otherwise:
            with w.block("else"):
                print_ops(w, op.otherwise, aod)
    elif isinstance(op, IfAwake):
        with w.block("if (!_aod)"):
            print_ops(w, op.body, aod)
    elif isinstance(op, Disagreement):
        print_ops(w, op.watch, aod)
    elif isinstance(op, Comment):
        w.comment(op.text)
    elif isinstance(op, Blank):
        w.blank()
    else:  # pragma: no cover - every Op is handled above
        raise TypeError(f"not an op: {op!r}")


def _print_text(w: Writer, op: Text, aod: AodStyle) -> None:
    x, y = num_code(op.x, aod), num_code(op.y, aod)
    justify = " | ".join(f"Graphics.{flag}" for flag in op.justify)
    value = str_code(op.text, aod)
    font = op.font.code
    if op.style == "angled":
        assert op.angle is not None
        w.call("dc.drawAngledText", [f"{x}, {y}, {font}, {value}",
                                     f"{justify}, {num_code(op.angle, aod)}"])
    elif op.style == "radial":
        assert op.angle is not None and op.radius is not None
        direction = shapes.RADIAL_DIRECTION[op.direction or "clockwise"]
        radius = shapes.radial_radius_expr(num_code(op.radius, aod), op.valign, op.direction,
                                           font)
        w.call("dc.drawRadialText", [f"{x}, {y}, {font}, {value}",
                                     f"{justify}, {num_code(op.angle, aod)}, {radius}",
                                     f"Graphics.{direction}"])
    else:
        _print_upright(w, op.x, op.y, font, op.text, op.justify, op.valign, aod)


def _print_upright(w: Writer, x: Num, y: Num, font: str, text: Str, justify: tuple[str, ...],
                   valign: str, aod: AodStyle) -> None:
    """An upright `dc.drawText`: `vertical_align: bottom` moves `y` up by the
    font's height (`glyph_y_expr`), which no justify flag can."""
    flags = " | ".join(f"Graphics.{flag}" for flag in justify)
    w.call("dc.drawText", [
        f"{num_code(x, aod)}, {glyph_y_expr(num_code(y, aod), valign, font)}, {font}",
        str_code(text, aod), flags])
