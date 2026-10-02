"""Backend 1: a draw program as the Monkey C body of `draw<Id>`.

It writes through the emitter's own `Writer` (`call`, `block`, `blank`) and
its spelling helpers (`shifted`, `plus`, `glyph_y_expr`,
`radial_radius_expr`, `mc_color`), so a ported kind prints exactly what its
hand-written `emit_draw` printed.
"""

from __future__ import annotations

from collections.abc import Iterable

from .. import formatting
from ..emit.monkeyc import rotated, shapes
from ..emit.monkeyc.common import NO_AOD, AodStyle, glyph_y_expr, mc_color, mc_float, plus
from ..emit.writer import Writer
from ..ir import local_name
from .program import (
    AodDimmed, AodPaint, AodPart, AodPick, AodRestyled, AodStr, ArcProgress, ArcSpan, Assign, Bin,
    AnyOf, Blank, Call, Cmp, Color, Comment, Concat, Cond, Const, Continue, Conv, Disagreement,
    FillPolygon, FloatLit, FontDrop, For, Glyph, HandAngle, IconChoice, If, IfAod, IfAwake, IfNotNull, Let, LetAutoScale,
    LetSlotPick, LetText, Lit, LoadFont, LocalsSet, Num, NumLocal, NumPick, Op, Paint,
    PaintPick, Paren, Part, PerCopy, Present, Primitive, Read, Reading, SetColor, SetPen, Shifted,
    NotSleeping, Str, StrLit, Text, Truthy, WrapperGuard,
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
    if isinstance(n, FloatLit):
        return mc_float(n.value) + n.suffix
    if isinstance(n, NumLocal):
        return n.name
    if isinstance(n, Read):
        return n.expr.code
    if isinstance(n, Bin):
        return f"{num_code(n.a, aod)} {n.op} {num_code(n.b, aod)}"
    if isinstance(n, Paren):
        return f"({num_code(n.inner, aod)})"
    if isinstance(n, Call):
        return f"{n.fn}({', '.join(num_code(arg, aod) for arg in n.args)})"
    if isinstance(n, Conv):
        return f"{num_code(n.inner, aod)}.{n.method}()"
    if isinstance(n, NumPick):
        return (f"({cond_code(n.cond, aod)}) ? {num_code(n.then, aod)} : "
                f"{num_code(n.otherwise, aod)}")
    if isinstance(n, FontDrop):
        return glyph_y_expr(num_code(n.base, aod), n.valign, n.font)
    if isinstance(n, HandAngle):
        return f"WfbHands.{n.function}(clock)"
    return plus(num_code(n.base, aod), str(n.by), n.times)


def cond_code(c: Cond, aod: AodStyle = NO_AOD) -> str:
    if isinstance(c, (Present, LocalsSet)):
        names = c.guards if isinstance(c, Present) else c.names
        return " && ".join(f"{name} != null" for name in names)
    if isinstance(c, Cmp):
        return f"{num_code(c.a, aod)} {c.op} {num_code(c.b, aod)}"
    if isinstance(c, AnyOf):
        return " || ".join(cond_code(term, aod) for term in c.conds)
    if isinstance(c, Truthy):
        return c.expr.code
    if isinstance(c, NotSleeping):
        return "!_sleeping"
    return f"_pulsing != {c.unique}"


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
    if isinstance(s, PerCopy):
        return str_code(s.printed, aod)
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
    if isinstance(c, AodPart):
        return aod.part_color(c.element, c.expr)
    if isinstance(c, PaintPick):
        return (f"({cond_code(c.cond, aod)}) ? {color_code(c.then, aod)} : "
                f"{color_code(c.otherwise, aod)}")
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
        w.line(f"dc.setColor({color_code(op.color, aod)}, Graphics.COLOR_TRANSPARENT);"
               + _note(op.note))
    elif isinstance(op, SetPen):
        w.line(f"dc.setPenWidth({n(op.width) if op.width is not None else '1'});"
               + _note(op.note))
    elif isinstance(op, Primitive):
        w.call(f"dc.{op.name}", [", ".join(n(v) for v in group) for group in op.args])
    elif isinstance(op, FillPolygon):
        w.line(f"dc.fillPolygon(Layout.{op.const});")
    elif isinstance(op, ArcSpan):
        if op.pen_first:
            w.call("WfbArc.drawSpan", [
                f"dc, {n(op.cx)}, {n(op.cy)}, {n(op.radius)}, {n(op.pen)}",
                f"{n(op.start)}, {n(op.sweep)}",
            ])
        else:
            w.call("WfbArc.drawSpan", [
                f"dc, {n(op.cx)}, {n(op.cy)}, {n(op.radius)}",
                f"{n(op.pen)}, {n(op.start)}, {n(op.sweep)}",
            ])
    elif isinstance(op, ArcProgress):
        w.call("WfbArc.drawProgress", [
            f"dc, {n(op.cx)}, {n(op.cy)}, {n(op.radius)}",
            f"{n(op.pen)}, {n(op.start)}, {n(op.sweep)}",
            n(op.fraction),
        ])
    elif isinstance(op, Part):
        assert not op.stamp, "a stamped part is only ever the preview side of a Disagreement"
        if op.ring is None:
            rotated.emit_transformed_part(w, op.part, op.prefix, radial=op.radial,
                                          thickness_expr=n(op.pen), set_pen=op.set_pen)
        else:
            rotated.emit_part_ring(w, op.part, op.prefix, op.ring, radial=op.radial,
                                   thickness_expr=n(op.pen), set_pen=op.set_pen)
    elif isinstance(op, Let):
        w.line(f"var {op.name} = {n(op.value)};" + _note(op.note))
    elif isinstance(op, Assign):
        w.line(f"{op.name} = {n(op.value)};")
    elif isinstance(op, If):
        with w.block(f"if ({cond_code(op.cond, aod)})"):
            print_ops(w, op.then, aod)
        if op.otherwise:
            with w.block("else"):
                print_ops(w, op.otherwise, aod)
    elif isinstance(op, For):
        with w.block(f"for (var {op.var} = 0; {op.var} < {n(op.bound)}; {op.var}++)"):
            print_ops(w, op.body, aod)
    elif isinstance(op, Continue):
        w.line("continue;")
    elif isinstance(op, LetSlotPick):
        w.line(f"var chosenId = {op.field};")
        if op.guarded:
            # the slot's Id field is null where Toybox.Complications is absent
            w.line("var chosenType = (chosenId != null) ? chosenId.getType() : null;")
            w.line("var pulled = (chosenId != null) ? WfbComplications.valueOf(chosenId) "
                   ": null;")
        else:
            w.line("var chosenType = chosenId.getType();")
            w.line("var pulled = WfbComplications.valueOf(chosenId);")
        w.line(f"var scale = (chosenType != null && pulled != null) "
               f"? {op.module}.scale(chosenType, pulled) : null;")
    elif isinstance(op, LetAutoScale):
        w.line(f"var scale = ({op.reader} != null) "
               f"? {op.module}.scale(Complications.{op.constant}, {op.reader}) : null;")
    elif isinstance(op, WrapperGuard):
        pass  # the view prints it
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


def _note(note: str) -> str:
    return f"  // {note}" if note else ""


def _print_text(w: Writer, op: Text, aod: AodStyle) -> None:
    x, y = num_code(op.x, aod), num_code(op.y, aod)
    justify = " | ".join(f"Graphics.{flag}" for flag in op.justify)
    value = str_code(op.text, aod)
    font = op.font.code
    if op.split_x:
        _print_split(w, op, x, y, font, value, justify, aod)
    elif op.style == "angled":
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
        _print_upright(w, op.x, op.y, font, op.text, op.justify,
                       op.valign if op.shift_y else "center", aod)


def _print_split(w: Writer, op: Text, x: str, y: str, font: str, value: str, justify: str,
                 aod: AodStyle) -> None:
    """A text call with its `x` on a line of its own: a pattern's text
    part.  Its `y` already carries any `bottom` drop (`FontDrop`)."""
    head = f"{y}, {font}, {value}"
    if op.style is None:
        w.call("dc.drawText", [x, head, justify])
        return
    assert op.angle is not None
    angle = num_code(op.angle, aod)
    if op.style == "angled":
        w.call("dc.drawAngledText", [x, head, f"{justify}, {angle}"])
        return
    assert op.radius is not None
    direction = shapes.RADIAL_DIRECTION[op.direction or "clockwise"]
    radius = shapes.radial_radius_expr(num_code(op.radius, aod), op.valign, op.direction, font)
    w.call("dc.drawRadialText", [x, head, f"{justify}, {angle}, {radius}",
                                 f"Graphics.{direction}"])


def _print_upright(w: Writer, x: Num, y: Num, font: str, text: Str, justify: tuple[str, ...],
                   valign: str, aod: AodStyle) -> None:
    """An upright `dc.drawText`: `vertical_align: bottom` moves `y` up by the
    font's height (`glyph_y_expr`), which no justify flag can."""
    flags = " | ".join(f"Graphics.{flag}" for flag in justify)
    w.call("dc.drawText", [
        f"{num_code(x, aod)}, {glyph_y_expr(num_code(y, aod), valign, font)}, {font}",
        str_code(text, aod), flags])
