"""Element emitters for `type: hands` and `type: pattern` -- geometry rotated on-device."""

from __future__ import annotations

import math

from ... import expr, formatting
from ...ir import PatternElement
from ...layout import PlacedHands, PlacedPattern
from .common import (
    AodDim, _aod_part_color, _aod_value, _color, _const_prefix, _field, _glyph_y_expr,
    _jitter_terms, _mc_float, _pattern_needs_math,
)
from .shapes import _RADIAL_DIRECTION, _emit_outline_loop, _radial_radius_expr
from ..writer import Writer


#: hand name -> the `WfbHands` function that turns the time into its angle.
_HAND_ANGLE_FUNCTIONS = (("hour", "hourAngle"), ("minute", "minuteAngle"), ("second", "secondAngle"))


def _emit_hands(w: Writer, placed: "PlacedHands", aod: bool = False, dim: AodDim = None) -> None:
    """`type: hands` -- one `sin`/`cos` pair per drawn hand, then rotate and
    draw each of its parts, shaped exactly like the analog-hands probe's
    `drawMainHands` (`docs/research/probes/analog-hands/`): the axis first,
    then hour, minute, second in that fixed order, with an `awake` second
    hand's parts wrapped in `if (!_sleeping)`.

    `aod: {color: ...}`/`{thickness: ...}` (plan 14 §5.1) apply uniformly to
    every part of every hand: one ternary against one element-level override,
    reused by every part's own colour/pen-width line, rather than a
    per-part override. With no `color:` override but a face-wide `dim`
    (§4.5), each part's own colour is dimmed instead -- `dim_effective` is
    `None` outright when this hand set is not shown in AOD at all
    (`element.aod is None`), matching `color_override`'s own guard.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    # `aod: {jitter: ...}` (plan 14 §5.2): every part rotates about (cx, cy)
    # -- shifting only this one declaration moves the whole hand assembly
    # rigidly, "the centre", with no change needed anywhere else in this
    # function or in `_emit_one_hand`/`_emit_rotated_part` below.
    jitter_dx, jitter_dy = _jitter_terms(placed, aod)
    w.line(f"var cx = Layout.{prefix}_CX{jitter_dx};")
    w.line(f"var cy = Layout.{prefix}_CY{jitter_dy};")
    color_override = (
        element.aod.color.code if (aod and element.aod is not None
                                   and element.aod.color is not None) else None
    )
    dim_effective = dim if (aod and element.aod is not None) else None
    thickness_override = (
        f"Layout.{prefix}_AOD_THICKNESS" if (aod and placed.aod_thickness is not None) else None
    )
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
                declared = _emit_one_hand(w, prefix, hand_name, angle_fn, hand, declared,
                                          color_override, thickness_override, aod, dim_effective)
        else:
            declared = _emit_one_hand(w, prefix, hand_name, angle_fn, hand, declared,
                                      color_override, thickness_override, aod, dim_effective)


def _emit_one_hand(w: Writer, prefix: str, hand_name: str, angle_fn: str, hand,
                   declared: bool, color_override: str | None = None,
                   thickness_override: str | None = None, aod: bool = False,
                   dim: AodDim = None) -> bool:
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
        color = _aod_part_color(part.color, color_override, aod, dim)
        if color != current:
            w.line(f"dc.setColor({color}, Graphics.COLOR_TRANSPARENT);")
            current = color
        _emit_rotated_part(w, part, part_prefix, thickness_override=thickness_override)
    return True


def _emit_rotated_part(w: Writer, part, part_prefix: str, *, set_pen: bool = True,
                       thickness_override: str | None = None) -> None:
    """One polygon/line/circle part's `WfbGeom.*Rotated` call about `(cx, cy)`
    -- shared by `_emit_one_hand` and a radial pattern's own
    `_emit_pattern_part`, which otherwise duplicate the exact two-line
    wrapping and `dc.setPenWidth(...)`/`dc.setPenWidth(1);` bracketing.  A
    hand never hoists its pen (``set_pen`` always true there); a radial
    pattern with one shared pen width across every line/outlined-circle part
    passes ``set_pen=False`` and brackets the whole loop itself instead.
    ``thickness_override``, when given, is the element-level
    `aod: {thickness: ...}` override's `Layout` constant, applied uniformly
    (plan 14 §5.1) to every part's own pen width, ternary against `_aod`.
    """
    if part.shape == "polygon":
        w.line(f"WfbGeom.fillRotated(dc, Layout.{part_prefix}_POINTS, cx, cy, sin, cos);")
    elif part.shape == "line":
        thickness_expr = _aod_value(
            thickness_override is not None, thickness_override, f"Layout.{part_prefix}_THICKNESS")
        if set_pen:
            w.line(f"dc.setPenWidth({thickness_expr});")
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
        thickness_expr = _aod_value(
            thickness_override is not None, thickness_override, f"Layout.{part_prefix}_THICKNESS")
        if set_pen:
            w.line(f"dc.setPenWidth({thickness_expr});")
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


def _emit_pattern_text_angle_expr(element: "PatternElement", part) -> str:
    """The per-copy Garmin-degrees angle a `shape: text` part's own
    `curve:` draws at (plan 11 slice 2) -- "the part's own local angle,
    composed with the copy's own rotation", the exact same composition a
    radial pattern's `arc` part's `start_angle` already gets one branch
    down (`_emit_pattern_part`'s arc case: `g0 = 90.0 - (part.start_angle +
    element.start_angle)`, then `g0 - i * step_deg` per copy).

    `part.curve_angle_garmin` is this part's own *local*, template-frame
    angle, for copy 0 alone (`wfb.layout.Resolver._resolve_hand_part` --
    the un-composed `HandPart.curve.angle`, run through `wfb.layout.
    garmin_curve_angle`). A radial pattern turns copy `i` by `element.
    start_angle + i * element.step_angle` design degrees, clockwise from
    12 -- the pattern's own rotation, always a *position*-style quantity
    regardless of the part's own `curve.style`, so composing it in still
    means subtracting it in Garmin's sign (the same "clockwise design
    degrees becomes a negative Garmin delta" fact `Angle.to_garmin`'s `90 -
    degrees` and `garmin_curve_angle`'s `angled` branch both rest on, an
    offset canceling out of any *difference* of two design-degree angles
    regardless of which one, if either, carried it). So copy `i`'s
    effective Garmin angle is `part.curve_angle_garmin - element.start_angle
    - i * element.step_angle` -- computed here as `g0 - i * step_deg` with
    `element.start_angle` folded into `g0` up front, the same shape the arc
    branch already uses, **whether the part's own `curve.style` is `angled`
    (a rotation, no offset in `part.curve_angle_garmin` to begin with) or
    `radial` (a position, `to_garmin`'s offset already folded into it)** --
    this function never needs to know which, since both compose with the
    copy's own rotation the same way. A linear pattern never rotates
    (`element.start_angle`/`.step_angle` are always `0.0` there, `wfb.
    layout.Resolver._resolve_pattern`), so `g0` reduces to `part.curve_
    angle_garmin` unchanged and every copy keeps this part's own local
    angle -- the "no copy angle to compose with" case plan 11 slice 2 asks
    for, with no special-casing needed here.
    """
    g0 = _mc_float(part.curve_angle_garmin - element.start_angle)
    if element.pattern == "radial":
        step_deg = _mc_float(element.step_angle)
        return f"{g0} - i * {step_deg}"
    return g0


def _emit_pattern_text_call(
    w: Writer, element: "PatternElement", part, part_prefix: str, radial: bool,
    font_expr: str, value_code: str, justify: str, x_expr: str, y_expr: str,
) -> None:
    """One `dc.drawText`/`drawAngledText`/`drawRadialText` call for one copy
    of a `shape: text` pattern part, at the given screen-space anchor --
    plain `dc.drawText` for an upright part (byte-identical to the code
    this project generated before plan 11 slice 2) or `dc.drawAngledText`/
    `dc.drawRadialText` under the part's own `curve:`.

    Split out of what was `_emit_pattern_text_draw` in its entirety before
    plan 15 §14 slice 2, so the interior pass and every `outline:` stamp
    can share one "anchor in, draw lines out" callback -- the same split
    `wfb.emit.monkeyc.shapes._emit_plain_text_call`/`_emit_vector_draw_call`
    already give a standalone element. `x_expr`/`y_expr` are always the
    caller's own already-rotated/translated (and, for a stamp, further
    offset) screen-space anchor -- never re-derived here -- which is what
    lets a screen-space `outline:` offset commute with the pattern's own
    rotation and the part's own `curve:` angle alike (research 14 §3.2):
    neither is touched by this function, only the two numbers plugged into
    `x_expr`/`y_expr` change between a stamp and the interior draw.
    """
    curve_style = part.curve_style
    if curve_style is None and not radial:
        # Byte-identical to the pre-slice-2 shape: x, y and font share one
        # line, the value its own, justify its own.
        lines = [
            f"dc.drawText({x_expr}, {y_expr}, {font_expr},",
            f"            {value_code},",
            f"            {justify});",
        ]
    elif curve_style is None:
        pad = " " * len("dc.drawText(")
        lines = [
            f"dc.drawText({x_expr},",
            f"{pad}{y_expr}, {font_expr}, {value_code},",
            f"{pad}{justify});",
        ]
    elif curve_style == "angled":
        angle_expr = _emit_pattern_text_angle_expr(element, part)
        pad = " " * len("dc.drawAngledText(")
        lines = [
            f"dc.drawAngledText({x_expr},",
            f"{pad}{y_expr}, {font_expr}, {value_code},",
            f"{pad}{justify}, {angle_expr});",
        ]
    else:  # "radial"
        angle_expr = _emit_pattern_text_angle_expr(element, part)
        direction = _RADIAL_DIRECTION[part.curve_direction or "clockwise"]
        radius_expr = _radial_radius_expr(f"Layout.{part_prefix}_RADIUS", part.vertical_align,
                                          part.curve_direction, font_expr)
        pad = " " * len("dc.drawRadialText(")
        lines = [
            f"dc.drawRadialText({x_expr},",
            f"{pad}{y_expr}, {font_expr}, {value_code},",
            f"{pad}{justify}, {angle_expr}, {radius_expr},",
            f"{pad}Graphics.{direction});",
        ]
    for line in lines:
        w.line(line)


def _emit_pattern_text_draw(
    w: Writer, element: "PatternElement", part, part_prefix: str, radial: bool,
    font_expr: str, value_code: str, justify: str,
) -> None:
    """One copy's `shape: text` part: this copy's own anchor, then --
    ahead of the interior pass, inside the same vector-font null guard --
    the part's own `outline:` stamp loop, if it has one (plan 15 §14
    slice 2), then the interior call itself (`_emit_pattern_text_call`).

    **Gate 4 is never omitted, on any device, in either `if_unavailable:`
    mode** (`docs/research/12-vector-fonts.md` §1, `wfb.emit.monkeyc.
    shapes._emit_vector_text_draw`'s own precedent): a vector font's draw
    call is wrapped `if (<font local> != null)` regardless of `curve_style`
    -- an upright vector-font pattern text part needs the same null guard a
    curved one does, since `Graphics.getVectorFont` can return null even
    when every build-time gate passed. `font_expr` is already a *local*,
    loaded once before the copy loop by `_emit_pattern` (never a repeated
    field access), so this is a plain local `if`, not the field-narrowing
    trap `docs/lore/monkeyc.md` warns about. A baked custom font never
    reaches this guard: `_emit_pattern`'s own pre-loop loading early-returns
    on a null baked font instead (a structural resource-load failure, not
    the ordinary case a vector font's null is), so `part.font_is_vector`
    alone decides which of the two this part gets. `outline:`'s stamp loop
    and the interior call both move inside this one guard together, never
    two guards -- the same shape `_emit_vector_text_draw` already uses for
    a standalone element (plan 15 §5/§8).

    **The ring colour, and its own `dc.setColor` restore, are entirely
    local to this one part's own draw sequence** -- they do not interact
    with `_emit_pattern`'s own colour hoisting (`hoist_color`/
    `current_color`, tracking each part's *interior* `color:` across the
    whole per-copy loop): the sequence below always leaves `dc`'s colour
    state at `part.color`'s own value by the time it returns, exactly the
    value the outer loop already believed was current both before and
    after, so the outer loop's own bookkeeping needs no change.
    """
    curve_style = part.curve_style
    if radial:
        # `bottom` shifts the shared `cy` translation term only for this
        # call, not the variable itself (other parts of the same copy
        # still rotate about the unshifted origin) -- the subtraction
        # lands outside the rotation, so it moves the drawn point
        # straight up on screen regardless of `theta`. Skipped entirely
        # under `curve:`: `vertical_align: bottom` is rejected there
        # (`Builder._build_pattern_curve`), and `center`/`top` need no
        # y-shift -- `curve:`'s own vertical alignment is a `justify` flag,
        # never a coordinate shift (plan 11 §2.3).
        cy_expr = "cy" if curve_style is not None else _glyph_y_expr(
            "cy", part.vertical_align, font_expr)
        x_expr = (
            f"WfbGeom.rotatedX(Layout.{part_prefix}_X, "
            f"Layout.{part_prefix}_Y, cx, sin, cos)"
        )
        y_expr = (
            f"WfbGeom.rotatedY(Layout.{part_prefix}_X, "
            f"Layout.{part_prefix}_Y, {cy_expr}, sin, cos)"
        )
    else:
        x_expr = f"ox + Layout.{part_prefix}_X"
        oy_expr = f"oy + Layout.{part_prefix}_Y"
        y_expr = oy_expr if curve_style is not None else _glyph_y_expr(
            oy_expr, part.vertical_align, font_expr)

    def draw() -> None:
        if part.outline_color is not None:
            # `index_var`/`offsets_var` are unique per part (`part_prefix`
            # already is, `_emit_pattern_part`'s own precedent for every
            # other per-part constant name) -- the copy loop wrapping this
            # whole method already declares its own `var i`, and more than
            # one outlined text part in the same pattern shares this one
            # generated method too, so the offset loop cannot reuse the
            # plain `i`/`offsets` names slice 1 uses for a standalone
            # element (`_emit_outline_loop`'s own docstring).
            _emit_outline_loop(
                w, part.outline_width, _color(part.outline_color), x_expr, y_expr,
                lambda ox_, oy_: _emit_pattern_text_call(
                    w, element, part, part_prefix, radial, font_expr, value_code, justify,
                    ox_, oy_),
                index_var=f"outlineI{part_prefix}", offsets_var=f"outlineOffsets{part_prefix}",
            )
            w.line(f"dc.setColor({_color(part.color)}, Graphics.COLOR_TRANSPARENT);")
        _emit_pattern_text_call(
            w, element, part, part_prefix, radial, font_expr, value_code, justify,
            x_expr, y_expr)

    if part.font_is_vector:
        with w.block(f"if ({font_expr} != null)"):
            draw()
    else:
        draw()


def _emit_pattern_part(w: Writer, element: "PatternElement", prefix: str, index: int,
                       part, radial: bool, hoist_pen: bool,
                       text_fonts: dict[str, str] | None = None,
                       thickness_override: str | None = None) -> None:
    """One template part, drawn for the current copy `i`: rotated about
    `(cx, cy)` through `WfbGeom` for a radial pattern, translated by
    `(ox, oy)` for a linear one -- the same two drawing shapes
    `_emit_one_hand` already uses for a hand, generalised from "the axis" to
    "this copy's origin".  An `arc` part is the one shape neither calling
    convention covers on its own: it always goes through `WfbArc.drawSpan`,
    radial or linear alike, with the centre as its only per-copy input (an
    arc part is never `at:`-offset).  A `text` part is the other one-off:
    only its *anchor* moves -- `WfbGeom.rotatedX`/`rotatedY` feed straight into
    `dc.drawText` for radial (split from a single `drawTextRotated` call,
    which was a 10th-parameter over CIQ 3.x's ceiling -- see that function's
    own docstring), a plain `dc.drawText(ox + ..., oy + ..., ...)` for
    linear, no helper needed there since a linear pattern never rotates
    anything -- **unless the part's own `curve:` turns the glyphs too**
    (plan 11 slice 2), in which case `_emit_pattern_text_draw` draws
    `dc.drawAngledText`/`dc.drawRadialText` at that same rotated/translated
    anchor instead, with the per-copy angle `_emit_pattern_text_angle_expr`
    computes.  Its value is either the part's own
    `text:` literal or its `value:` compiled through `formatting.emit` (the
    same call `_emit_text` makes for a `text` element), read off
    `element.parts[index]` -- the *IR* part, which is what carries
    `text_value`/`text_literal` (geometry resolution in `wfb.layout` never
    touches them).  ``text_fonts`` maps a custom font's resource name to the
    local variable `_emit_pattern` already loaded it into, before the loop --
    for a `face:` (vector) font, that local is never early-return-guarded
    the way a baked one is (see `_emit_pattern_text_draw`'s own docstring).
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
        _emit_pattern_text_draw(w, element, part, part_prefix, radial, font_expr, value_code, justify)
        return
    if part.shape == "polygon":
        if radial:
            _emit_rotated_part(w, part, part_prefix)
        else:
            w.line(f"WfbGeom.fillTranslated(dc, Layout.{part_prefix}_POINTS, ox, oy);")
        return
    if part.shape == "line":
        thickness_expr = _aod_value(
            thickness_override is not None, thickness_override, f"Layout.{part_prefix}_THICKNESS")
        if radial:
            _emit_rotated_part(w, part, part_prefix, set_pen=not hoist_pen,
                               thickness_override=thickness_override)
        else:
            if not hoist_pen:
                w.line(f"dc.setPenWidth({thickness_expr});")
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
        thickness_expr = _aod_value(
            thickness_override is not None, thickness_override, f"Layout.{part_prefix}_THICKNESS")
        if radial:
            _emit_rotated_part(w, part, part_prefix, set_pen=not hoist_pen,
                               thickness_override=thickness_override)
        else:
            if not hoist_pen:
                w.line(f"dc.setPenWidth({thickness_expr});")
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
    arc_thickness_expr = _aod_value(
        thickness_override is not None, thickness_override, f"Layout.{part_prefix}_THICKNESS")
    w.line(
        f"WfbArc.drawSpan(dc, {cx_arg}, {cy_arg}, Layout.{part_prefix}_RADIUS, "
        f"{arc_thickness_expr},"
    )
    w.line(f"                {start_arg}, {sweep});")


def _emit_pattern(w: Writer, placed: "PlacedPattern", aod: bool = False,
                  dim: AodDim = None) -> None:
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
    two parts naming the *same* font share one load and one guard.  **A
    `face:` (vector) font is the one exception to "guard once, before the
    loop"** (plan 11 slice 2): it is still loaded into a local once, but
    never early-return-guarded here -- gate 4 means it can be null on the
    ordinary "this device just doesn't have it" path, not only on a
    structural failure, and an early `return;` here would also cancel every
    *other* part of this same pattern sharing this one draw method, baked
    fonts and unrelated shapes included.  `_emit_pattern_text_draw` wraps
    its own draw call in the matching `if (<local> != null)` instead, once
    per copy, exactly as a standalone vector-font `text` element's own
    `_emit_vector_text_draw` already does.
    """
    element = placed.element
    prefix = _const_prefix(placed.id)
    # `aod: {color: ...}`/`{thickness: ...}` (plan 14 §5.1): one override,
    # applied uniformly to every part -- reused verbatim by every colour/pen
    # line below, whether hoisted or not.
    color_override = (
        element.aod.color.code if (aod and element.aod is not None
                                   and element.aod.color is not None) else None
    )
    dim_effective = dim if (aod and element.aod is not None) else None
    thickness_override = (
        f"Layout.{prefix}_AOD_THICKNESS" if (aod and placed.aod_thickness is not None) else None
    )
    # `aod: {jitter: ...}` (plan 14 §5.2): every copy's own `cx`/`cy`
    # (radial) or `ox`/`oy` (linear) derives from this one origin -- shifting
    # it moves the whole pattern rigidly, with no change needed anywhere
    # else in this function or in `_emit_pattern_part`/`_emit_pattern_text_
    # draw` below.
    jitter_dx, jitter_dy = _jitter_terms(placed, aod)
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
        w.line(f"var cx = Layout.{prefix}_X{jitter_dx};")
        w.line(f"var cy = Layout.{prefix}_Y{jitter_dy};")

    text_fonts: dict[str, str] = {}
    vector_text_fonts: set[str] = set()
    for _, part in live:
        if part.shape == "text" and part.font_is_custom and part.font_reference not in text_fonts:
            text_fonts[part.font_reference] = f"font{len(text_fonts)}"
            if part.font_is_vector:
                vector_text_fonts.add(part.font_reference)
    for reference, local in text_fonts.items():
        w.line(f"var {local} = _{_field(reference)};")
        if reference not in vector_text_fonts:
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
    colors = [_aod_part_color(part.color, color_override, aod, dim_effective)
             for _, part in live]
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
        hoisted_thickness_expr = _aod_value(
            thickness_override is not None, thickness_override,
            f"Layout.{prefix}_{hoist_index}_THICKNESS")
        w.line(f"dc.setPenWidth({hoisted_thickness_expr});"
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
            w.line(f"var ox = Layout.{prefix}_X{jitter_dx} + i * Layout.{prefix}_DX;")
            w.line(f"var oy = Layout.{prefix}_Y{jitter_dy} + i * Layout.{prefix}_DY;")
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
                    _emit_pattern_part(w, element, prefix, index, part, radial, hoist_pen,
                                       text_fonts, thickness_override)
            else:
                _emit_pattern_part(w, element, prefix, index, part, radial, hoist_pen,
                                   text_fonts, thickness_override)
    if hoist_pen:
        w.line("dc.setPenWidth(1);")
