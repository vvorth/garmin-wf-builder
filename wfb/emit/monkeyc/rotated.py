"""Element emitters for `type: hands` and `type: pattern` -- geometry rotated on-device."""

from __future__ import annotations

import math

from ... import expr, formatting
from ...ir import PatternElement
from ...layout import PlacedHands, PlacedPattern
from .common import _color, _const_prefix, _field, _glyph_y_expr, _mc_float, _pattern_needs_math
from ..writer import Writer


#: hand name -> the `WfbHands` function that turns the time into its angle.
_HAND_ANGLE_FUNCTIONS = (("hour", "hourAngle"), ("minute", "minuteAngle"), ("second", "secondAngle"))


def _emit_hands(w: Writer, placed: "PlacedHands") -> None:
    """`type: hands` -- one `sin`/`cos` pair per drawn hand, then rotate and
    draw each of its parts, shaped exactly like the analog-hands probe's
    `drawMainHands` (`docs/research/probes/analog-hands/`): the axis first,
    then hour, minute, second in that fixed order, with an `awake` second
    hand's parts wrapped in `if (!_sleeping)`.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    w.line(f"var cx = Layout.{prefix}_CX;")
    w.line(f"var cy = Layout.{prefix}_CY;")
    declared = False
    for hand_name, angle_fn in _HAND_ANGLE_FUNCTIONS:
        hand = getattr(placed, hand_name)
        if hand is None:
            continue
        gated = hand_name == "second" and element.seconds == "awake"
        w.blank()
        w.comment(f"{hand_name}" + (" -- seconds: awake" if gated else ""))
        if gated:
            with w.block("if (!_sleeping)"):
                declared = _emit_one_hand(w, prefix, hand_name, angle_fn, hand, declared)
        else:
            declared = _emit_one_hand(w, prefix, hand_name, angle_fn, hand, declared)


def _emit_one_hand(w: Writer, prefix: str, hand_name: str, angle_fn: str, hand,
                   declared: bool) -> bool:
    """One hand's angle/sin/cos, then each of its parts, rotated and drawn.

    `declared` says whether `angle`/`sin`/`cos` already have a `var` in this
    method -- the first hand declares them, every later one reuses the same
    three locals (the probe's own shape: Monkey C has no block scoping that
    would need a fresh declaration per hand).
    """
    keyword = "" if declared else "var "
    HAND = hand_name.upper()
    w.line(f"{keyword}angle = WfbHands.{angle_fn}(clock);")
    w.line(f"{keyword}sin = Math.sin(angle);")
    w.line(f"{keyword}cos = Math.cos(angle);")
    # One setColor per colour *change*: consecutive parts of one hand
    # usually share its default colour.  Reset per hand rather than
    # carried across hands, because an `awake` second hand sits inside its
    # own `if` block and cannot rely on a colour set before it.
    current = None
    for index, part in enumerate(hand.parts):
        part_prefix = f"{prefix}_{HAND}_{index}"
        color = _color(part.color)
        if color != current:
            w.line(f"dc.setColor({color}, Graphics.COLOR_TRANSPARENT);")
            current = color
        _emit_rotated_part(w, part, part_prefix)
    return True


def _emit_rotated_part(w: Writer, part, part_prefix: str, *, set_pen: bool = True) -> None:
    """One polygon/line/circle part's `WfbGeom.*Rotated` call about `(cx, cy)`
    -- shared by `_emit_one_hand` and a radial pattern's own
    `_emit_pattern_part`, which otherwise duplicate the exact two-line
    wrapping and `dc.setPenWidth(...)`/`dc.setPenWidth(1);` bracketing.  A
    hand never hoists its pen (``set_pen`` always true there); a radial
    pattern with one shared pen width across every line/outlined-circle part
    passes ``set_pen=False`` and brackets the whole loop itself instead.
    """
    if part.shape == "polygon":
        w.line(f"WfbGeom.fillRotated(dc, Layout.{part_prefix}_POINTS, cx, cy, sin, cos);")
    elif part.shape == "line":
        if set_pen:
            w.line(f"dc.setPenWidth(Layout.{part_prefix}_THICKNESS);")
        w.line(
            f"WfbGeom.drawLineRotated(dc, Layout.{part_prefix}_X1, "
            f"Layout.{part_prefix}_Y1,"
        )
        w.line(
            f"                        Layout.{part_prefix}_X2, "
            f"Layout.{part_prefix}_Y2, cx, cy, sin, cos);"
        )
        if set_pen:
            w.line("dc.setPenWidth(1);")
    elif part.filled:
        w.line(
            f"WfbGeom.fillCircleRotated(dc, Layout.{part_prefix}_X, "
            f"Layout.{part_prefix}_Y, Layout.{part_prefix}_RADIUS,"
        )
        w.line("                          cx, cy, sin, cos);")
    else:
        if set_pen:
            w.line(f"dc.setPenWidth(Layout.{part_prefix}_THICKNESS);")
        w.line(
            f"WfbGeom.drawCircleRotated(dc, Layout.{part_prefix}_X, "
            f"Layout.{part_prefix}_Y, Layout.{part_prefix}_RADIUS,"
        )
        w.line("                          cx, cy, sin, cos);")
        if set_pen:
            w.line("dc.setPenWidth(1);")


# --------------------------------------------------------------------------
# type: pattern


def _pattern_skip_condition(element: "PatternElement") -> str:
    """The loop's skip test, in one fixed order: `skip_every:` first, then
    every explicit `skip:` index it does not already cover -- an index
    `skip_every:` already catches would otherwise test true a second time
    for no reason.  Empty when nothing is skipped, which is what lets
    :func:`_emit_pattern` omit the `if` entirely.
    """
    terms: list[str] = []
    if element.skip_every is not None:
        terms.append(f"i % {element.skip_every} == 0")
    for index in element.skip:
        if element.skip_every is None or index % element.skip_every != 0:
            terms.append(f"i == {index}")
    return " || ".join(terms)


def _pattern_angle_expr(element: "PatternElement") -> tuple[str, str]:
    """The radial loop's `angle` expression (radians, bare `Float`
    literals) and the degrees comment beside it: `<start> + i * <step>`,
    with the start term dropped from the *code* when `start: 0deg` (the
    common case) -- the comment always spells out both numbers, so the
    general rule stays visible even then.
    """
    step_rad = _mc_float(math.radians(element.step_angle))
    comment = f"({element.start_angle:g} + {element.step_angle:g} i) degrees"
    if element.start_angle == 0.0:
        return f"i * {step_rad}", comment
    start_rad = _mc_float(math.radians(element.start_angle))
    return f"{start_rad} + i * {step_rad}", comment


def _emit_pattern_part(w: Writer, element: "PatternElement", prefix: str, index: int,
                       part, radial: bool, hoist_pen: bool,
                       text_fonts: dict[str, str] | None = None) -> None:
    """One template part, drawn for the current copy `i`: rotated about
    `(cx, cy)` through `WfbGeom` for a radial pattern, translated by
    `(ox, oy)` for a linear one -- the same two drawing shapes
    `_emit_one_hand` already uses for a hand, generalised from "the axis" to
    "this copy's origin".  An `arc` part is the one shape neither calling
    convention covers on its own: it always goes through `WfbArc.drawSpan`,
    radial or linear alike, with the centre as its only per-copy input (an
    arc part is never `at:`-offset).  A `text` part is the other one-off:
    only its *anchor* moves -- `WfbGeom.drawTextRotated` for radial, a plain
    `dc.drawText(ox + ..., oy + ..., ...)` for linear, no helper needed there
    since a linear pattern never rotates anything.  Its value is either the part's own
    `text:` literal or its `value:` compiled through `formatting.emit` (the
    same call `_emit_text` makes for a `text` element), read off
    `element.parts[index]` -- the *IR* part, which is what carries
    `text_value`/`text_literal` (geometry resolution in `wfb.layout` never
    touches them).  ``text_fonts`` maps a custom font's resource name to the
    local variable `_emit_pattern` already loaded it into, before the loop.
    """
    part_prefix = f"{prefix}_{index}"
    if part.shape == "text":
        ir_part = element.parts[index]
        if ir_part.text_literal is not None:
            escaped = ir_part.text_literal.replace("\\", "\\\\").replace('"', '\\"')
            value_code = f'"{escaped}"'
        else:
            value_code = formatting.emit(
                ir_part.format or "{}",
                ir_part.text_value.code,
                ir_part.text_value.value.type,
            )
        justify = " | ".join(f"Graphics.{flag}" for flag in part.justify)
        if part.font_is_custom:
            font_expr = (text_fonts or {})[part.font_reference]
        else:
            font_expr = f"Graphics.{part.font_reference}"
        if radial:
            # `bottom` shifts the shared `cy` translation term only for this
            # call, not the variable itself (other parts of the same copy
            # still rotate about the unshifted origin) -- the subtraction
            # lands outside the rotation, so it moves the drawn point
            # straight up on screen regardless of `theta`.
            cy_expr = _glyph_y_expr("cy", part.vertical_align, font_expr)
            pad = " " * len("WfbGeom.drawTextRotated(")
            w.line(
                f"WfbGeom.drawTextRotated(dc, Layout.{part_prefix}_X, "
                f"Layout.{part_prefix}_Y,"
            )
            w.line(f"{pad}cx, {cy_expr}, sin, cos, {font_expr}, {value_code},")
            w.line(f"{pad}{justify});")
        else:
            y_expr = _glyph_y_expr(
                f"oy + Layout.{part_prefix}_Y", part.vertical_align, font_expr)
            w.line(f"dc.drawText(ox + Layout.{part_prefix}_X, {y_expr}, {font_expr},")
            w.line(f"            {value_code},")
            w.line(f"            {justify});")
        return
    if part.shape == "polygon":
        if radial:
            _emit_rotated_part(w, part, part_prefix)
        else:
            w.line(f"WfbGeom.fillTranslated(dc, Layout.{part_prefix}_POINTS, ox, oy);")
        return
    if part.shape == "line":
        if radial:
            _emit_rotated_part(w, part, part_prefix, set_pen=not hoist_pen)
        else:
            if not hoist_pen:
                w.line(f"dc.setPenWidth(Layout.{part_prefix}_THICKNESS);")
            w.line(f"dc.drawLine(ox + Layout.{part_prefix}_X1, oy + Layout.{part_prefix}_Y1,")
            w.line(f"            ox + Layout.{part_prefix}_X2, oy + Layout.{part_prefix}_Y2);")
            if not hoist_pen:
                w.line("dc.setPenWidth(1);")
        return
    if part.shape == "circle":
        if part.filled:
            if radial:
                _emit_rotated_part(w, part, part_prefix)
            else:
                w.line(
                    f"dc.fillCircle(ox + Layout.{part_prefix}_X, "
                    f"oy + Layout.{part_prefix}_Y, Layout.{part_prefix}_RADIUS);"
                )
            return
        if radial:
            _emit_rotated_part(w, part, part_prefix, set_pen=not hoist_pen)
        else:
            if not hoist_pen:
                w.line(f"dc.setPenWidth(Layout.{part_prefix}_THICKNESS);")
            w.line(
                f"dc.drawCircle(ox + Layout.{part_prefix}_X, "
                f"oy + Layout.{part_prefix}_Y, Layout.{part_prefix}_RADIUS);"
            )
            if not hoist_pen:
                w.line("dc.setPenWidth(1);")
        return
    # arc: always centred on the copy's own origin.  A radial pattern
    # turns the author start angle by plain degree subtraction -- the same
    # arithmetic `wfb.layout.garmin_arc` performs at build time for a
    # standalone `shape: arc`, just with `i * step` folded in at runtime --
    # so copy 0 of a radial pattern's arc reaches `WfbArc.drawSpan` with
    # exactly the numbers a `shape: arc` of the same angles would.  A
    # linear pattern never turns at all, so its arc keeps copy 0's angles
    # unchanged at every copy, and only its centre moves.
    g0 = _mc_float(90.0 - (part.start_angle + element.start_angle))
    sweep = _mc_float(part.sweep)
    if radial:
        step_deg = _mc_float(element.step_angle)
        start_arg = f"{g0} - i * {step_deg}"
        cx_arg, cy_arg = "cx", "cy"
    else:
        start_arg = g0
        cx_arg, cy_arg = "ox", "oy"
    w.line(
        f"WfbArc.drawSpan(dc, {cx_arg}, {cy_arg}, Layout.{part_prefix}_RADIUS, "
        f"Layout.{part_prefix}_THICKNESS,"
    )
    w.line(f"                {start_arg}, {sweep});")


def _emit_pattern(w: Writer, placed: "PlacedPattern") -> None:
    """`type: pattern` -- loop over the drawn copies, turning (radial) or
    translating (linear) the template resolved once at build time.  The
    same bargain `_emit_hands` already struck for analog hands: the device
    performs the one piece of layout arithmetic ADR 0004 leaves it (a
    rotation or a translation), everything else is a `Layout` constant.

    Per-copy part `visible:`: a part whose `visible:` folded to a
    compile-time `false` is dropped here entirely -- no colour line, no
    draw call -- the `dead-element` lint already told the author. A part
    whose `visible:` is not constant is *gated*: its own drawing (everything
    `_emit_pattern_part` writes for it, pen included) sits inside
    `if (<condition>) { ... }`, but its `dc.setColor(...)` stays where it
    already was, **before** the gate and unconditional -- so the pen colour
    after this part is the same whichever branch ran, and the part *after*
    it never has to ask whether this one actually drew.

    A `text` part's custom font is loaded into a local **once, before the
    loop** -- the same "load once, guard once" rule `_emit_text_draw` follows
    for a standalone `text` element, just hoisted out of the per-copy body
    since every copy shares one font.  Two text parts naming different fonts
    get two distinct locals (``font0``, ``font1``, ...), so nothing collides;
    two parts naming the *same* font share one load and one guard.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    # `element.parts[i]` and `placed.parts[i]` are the same template, in the
    # same order (`Resolver._resolve_pattern` builds one `ResolvedHandPart`
    # per `HandPart`, 1:1) -- so the IR part is what carries `visible:`
    # (geometry resolution never touches it), read here by plain index.
    live = [
        (index, part) for index, part in enumerate(placed.parts)
        if not (element.parts[index].visible is not None
                and element.parts[index].visible.is_constant)
    ]
    radial = element.pattern == "radial"
    needs_trig = _pattern_needs_math(placed)

    if radial:
        w.line(f"var cx = Layout.{prefix}_X;")
        w.line(f"var cy = Layout.{prefix}_Y;")

    text_fonts: dict[str, str] = {}
    for _, part in live:
        if part.shape == "text" and part.font_is_custom and part.font_reference not in text_fonts:
            text_fonts[part.font_reference] = f"font{len(text_fonts)}"
    for reference, local in text_fonts.items():
        w.line(f"var {local} = _{_field(reference)};")
        with w.block(f"if ({local} == null)"):
            w.line("return;  // the font resource failed to load")
        w.blank()

    # Colour: one distinct part colour is set once, before the loop; several
    # are set inside it, only on each change (the same rule `_emit_one_hand`
    # already follows within one hand).  A colour that reads `copy` is the
    # loop's own `i`, so it can never be hoisted: it is set inside the loop,
    # afresh on every copy.  (A data reading needs no such care -- its local
    # is declared at the top of the method, before the loop.)  A dead part
    # (constant-false `visible:`, excluded from `live`) contributes no
    # colour at all -- it never draws, so its colour is nobody's concern.
    colors = [_color(part.color) for _, part in live]
    distinct_colors = list(dict.fromkeys(colors))
    per_copy = any(expr.reads_copy(part.color.ast) for _, part in live
                   if part.color is not None)
    hoist_color = len(distinct_colors) == 1 and not per_copy

    # Pen width: hoisted when every line/outlined-circle part shares one
    # width and there is no arc part -- `WfbArc.drawSpan` resets the pen to
    # 1 itself on every call, which would undo a hoisted width on the very
    # next copy.
    pen_parts = [(i, part) for i, part in live
                if part.shape == "line" or (part.shape == "circle" and not part.filled)]
    has_arc = any(part.shape == "arc" for _, part in live)
    hoist_pen = (
        bool(pen_parts) and not has_arc
        and len({p.thickness for _, p in pen_parts}) == 1
    )

    if hoist_color:
        w.line(f"dc.setColor({distinct_colors[0]}, Graphics.COLOR_TRANSPARENT);"
              "  // hoisted: one colour")
    if hoist_pen:
        hoist_index = pen_parts[0][0]
        w.line(f"dc.setPenWidth(Layout.{prefix}_{hoist_index}_THICKNESS);"
              "  // hoisted: one pen, no arc")

    skip_condition = _pattern_skip_condition(element)
    with w.block(f"for (var i = 0; i < {element.count}; i++)"):
        if skip_condition:
            with w.block(f"if ({skip_condition})"):
                w.line("continue;")
        if radial:
            if needs_trig:
                angle_expr, angle_comment = _pattern_angle_expr(element)
                w.line(f"var angle = {angle_expr};  // {angle_comment}")
                w.line("var sin = Math.sin(angle);")
                w.line("var cos = Math.cos(angle);")
        else:
            w.line(f"var ox = Layout.{prefix}_X + i * Layout.{prefix}_DX;")
            w.line(f"var oy = Layout.{prefix}_Y + i * Layout.{prefix}_DY;")
        current_color = distinct_colors[0] if hoist_color else None
        for color, (index, part) in zip(colors, live):
            if not hoist_color and color != current_color:
                w.line(f"dc.setColor({color}, Graphics.COLOR_TRANSPARENT);")
                current_color = color
            visible = element.parts[index].visible
            if visible is not None:
                # Non-constant, or `live` would have excluded it above.
                w.comment(f"visible: {visible.text}")
                with w.block(f"if ({visible.code})"):
                    _emit_pattern_part(w, element, prefix, index, part, radial, hoist_pen, text_fonts)
            else:
                _emit_pattern_part(w, element, prefix, index, part, radial, hoist_pen, text_fonts)
    if hoist_pen:
        w.line("dc.setPenWidth(1);")
