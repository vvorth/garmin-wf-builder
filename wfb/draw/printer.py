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
from ..emit.monkeyc.common import glyph_y_expr, mc_color, plus
from ..emit.writer import Writer
from .program import (
    ArcSpan, Blank, Color, Comment, Concat, Const, FillPolygon, IfAod, IfNotNull, LetText, Lit,
    LoadFont, Num, Op, Primitive, Reading, SetColor, SetPen, Shifted, Str, StrLit, Text,
)


def num_code(n: Num) -> str:
    if isinstance(n, Const):
        return f"Layout.{n.name}"
    if isinstance(n, Lit):
        return str(int(n.value)) if float(n.value).is_integer() else repr(n.value)
    if isinstance(n, Shifted):
        return shapes.shifted(num_code(n.base), n.by)
    return plus(num_code(n.base), str(n.by), n.times)


def str_code(s: Str) -> str:
    if isinstance(s, StrLit):
        return f'"{s.text}"'
    if isinstance(s, Reading):
        return formatting.emit(s.spec, s.value.code, s.value.value.type,
                               unit_code=s.unit.code if s.unit is not None else None)
    if isinstance(s, Concat):
        return " + ".join(str_code(part) for part in s.parts)
    return s.name


def color_code(c: Color) -> str:
    return mc_color(c.expr)


def print_ops(w: Writer, ops: Iterable[Op]) -> None:
    """Write ``ops`` into ``w``, in order."""
    for op in ops:
        _print(w, op)


def _print(w: Writer, op: Op) -> None:
    if isinstance(op, SetColor):
        w.line(f"dc.setColor({color_code(op.color)}, Graphics.COLOR_TRANSPARENT);")
    elif isinstance(op, SetPen):
        w.line(f"dc.setPenWidth({num_code(op.width) if op.width is not None else '1'});")
    elif isinstance(op, Primitive):
        w.call(f"dc.{op.name}", [", ".join(num_code(n) for n in group) for group in op.args])
    elif isinstance(op, FillPolygon):
        w.line(f"dc.fillPolygon(Layout.{op.const});")
    elif isinstance(op, ArcSpan):
        w.call("WfbArc.drawSpan", [
            f"dc, {num_code(op.cx)}, {num_code(op.cy)}, {num_code(op.radius)}",
            f"{num_code(op.pen)}, {num_code(op.start)}, {num_code(op.sweep)}",
        ])
    elif isinstance(op, LoadFont):
        w.line(f"var {op.local} = _{op.field};")
        if op.on_null == "return":
            with w.block(f"if ({op.local} == null)"):
                w.line("return;  // the font resource failed to load")
    elif isinstance(op, Text):
        _print_text(w, op)
    elif isinstance(op, LetText):
        w.line(f"var {op.name} = {str_code(op.initial)};")
        available = " && ".join(f"{guard} != null" for guard in op.guards)
        with w.block(f"if ({available})"):
            w.line(f"{op.name} = {str_code(op.value)};")
    elif isinstance(op, IfNotNull):
        with w.block(f"if ({op.local} != null)"):
            print_ops(w, op.body)
    elif isinstance(op, IfAod):
        with w.block("if (_aod)"):
            print_ops(w, op.then)
        if op.otherwise:
            with w.block("else"):
                print_ops(w, op.otherwise)
    elif isinstance(op, Comment):
        w.comment(op.text)
    elif isinstance(op, Blank):
        w.blank()
    else:  # pragma: no cover - every Op is handled above
        raise TypeError(f"not an op: {op!r}")


def _print_text(w: Writer, op: Text) -> None:
    x, y = num_code(op.x), num_code(op.y)
    justify = " | ".join(f"Graphics.{flag}" for flag in op.justify)
    value = str_code(op.text)
    font = op.font.code
    if op.style == "angled":
        assert op.angle is not None
        w.call("dc.drawAngledText", [f"{x}, {y}, {font}, {value}",
                                     f"{justify}, {num_code(op.angle)}"])
    elif op.style == "radial":
        assert op.angle is not None and op.radius is not None
        direction = shapes.RADIAL_DIRECTION[op.direction or "clockwise"]
        radius = shapes.radial_radius_expr(num_code(op.radius), op.valign, op.direction, font)
        w.call("dc.drawRadialText", [f"{x}, {y}, {font}, {value}",
                                     f"{justify}, {num_code(op.angle)}, {radius}",
                                     f"Graphics.{direction}"])
    else:
        w.call("dc.drawText", [f"{x}, {glyph_y_expr(y, op.valign, font)}, {font}",
                               value, justify])
