"""`type: pattern` -- one template of 1-16 primitives, drawn repeatedly:
turned about `at:` (`pattern: radial`), stepped along `{dx, dy}`
(`pattern: linear`), or stepped in rows of `columns:` (`pattern: grid`)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import math
from dataclasses import dataclass

from .. import expr, formatting
from ..catalog import Type
from ..ir.builder import ABSENCE_IS_NORMAL, and_paths, dedup_append
from ..ir import disc_perimeter_offsets
from ..ir.model import (
    AnyHandPart, Element, Expression, PATTERN_LOOP_INDEX, PatternElement, Position,
    ROLE_COLOR, ROLE_PART_VISIBLE, drawn_copies,
)
from ..layout import (
    Ink, Placed, PlacedPattern, ResolvedHandPart, ResolvedTextPart,
    round_half_away, text_ink,
)
from ..units import Axis, Box, IntBox
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc.common import const_prefix, font_field
from ..draw.printer import color_code
from ..draw.program import (
    AnyOf, AodDimmed, AodPart, AodPick, ArcSpan, Bin, Blank, Call, Cmp, Comment, Cond, Const,
    Continue, DrawContext, FloatLit, Font, FontDrop, For, If, IfNotNull, Let, Lit,
    LoadFont, Num, NumLocal, Op, Paint, Paren, Part, PerCopy, Reading, RingColor, SetColor, SetPen,
    Shifted, Str, StrLit, Text, Truthy,
)
from . import ElementKind, TextRun

if TYPE_CHECKING:
    from collections.abc import Iterator

    from . import ContrastSubject
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..layout import Resolver


@dataclass(frozen=True)
class PatternTextAngle:
    """The terms of the per-copy Garmin-degrees angle a `shape: text`
    pattern part's own `curve:` draws at:
    `local` -- the part's own local, copy-0 angle (`part.curve.angle_garmin`);
    `start`/`step` -- the pattern's own repeat angle, design degrees
    clockwise from 12 (`0.0`/`0.0` for a linear pattern, which then leaves
    every copy at the local angle unchanged).  One definition of the
    composition, shared by the lint ink (`_pattern_text_ink`, via
    :meth:`copy_curve_angle`) and the draw program (`_text_angle`, which
    reads `local`/`start`/`step` off this same object but builds a program
    value from them -- `start` folded into a literal with `local`, `step`
    multiplied by the runtime copy index -- that the watch and the preview
    both compute).
    """

    local: float
    start: float
    step: float

    def copy_curve_angle(self, index: int) -> float:
        """`(local - (start + index * step)) % 360.0` -- the expression
        order the lint box has always used, kept so it never moves."""
        return (self.local - (self.start + index * self.step)) % 360.0


def pattern_text_anchor(
    part: ResolvedTextPart, ox: float, oy: float, sin_t: float, cos_t: float,
) -> tuple[int, int]:
    """The whole-pixel anchor point of one copy of a `shape: text` pattern
    part: the template-frame point ``(part.x, part.y)``
    put through this copy's :meth:`PlacedPattern.transform`, then rounded
    **half up** (``floor(v + 0.5)``, not `round_half_away`'s half-*away-from-
    zero* -- a hand-frame mirror-symmetry rule that does not apply here) --
    the device does the same ``(v + 0.5).toNumber()`` (`runtime-lib/
    WfbGeom.mc`), so the preview pixel and the device pixel agree.  A
    module-level function, not a method, so codegen and the preview can
    share it without importing a `Resolver`.
    """
    tx = ox + part.x * cos_t - part.y * sin_t
    ty = oy + part.x * sin_t + part.y * cos_t
    return math.floor(tx + 0.5), math.floor(ty + 0.5)


def _pattern_text_ink(
    part: ResolvedTextPart, ox: float, oy: float, sin_t: float, cos_t: float, index: int,
    start: float, step: float, fonts_root: str | None = None,
) -> Ink:
    """:func:`text_ink` for copy `index` of a `shape: text` pattern part:
    anchored at :func:`pattern_text_anchor`, measured by that copy's own
    string (``part.widths[index]``), and -- under `curve:` -- turned by the
    part's local angle composed with the copy's own rotation
    (`start`/`step`, design degrees clockwise from 12; `0.0`/`0.0` for a
    linear pattern) through :class:`PatternTextAngle`, the same composition
    `_text_angle` draws at.
    `fonts_root`: see :func:`text_ink`.
    """
    ax, ay = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
    angle_garmin = PatternTextAngle(part.curve.angle_garmin, start, step).copy_curve_angle(index)
    return text_ink(
        ax, ay, part.widths[index] if part.widths else 0, part.line_height,
        part.align, part.vertical_align, curve_style=part.curve.style,
        angle_garmin=angle_garmin,
        radius_px=part.curve.radius_px, direction=part.curve.direction,
        metric=part.font.metric, pad=float(part.outline_width), fonts_root=fonts_root)


def _pattern_part_ink(
    part: ResolvedHandPart, ox: float, oy: float, sin_t: float, cos_t: float, index: int,
    start: float = 0.0, step: float = 0.0, fonts_root: str | None = None,
) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of one resolved pattern part's ink
    for one copy, given that copy's :meth:`PlacedPattern.transform`: the
    part's own `ink`, or for a text part :func:`_pattern_text_ink` -- the
    one shape that needs to know *which* copy it is, since upright text is
    not rotation-invariant and each copy draws its own string.  `start`/
    `step` are the pattern's own repeat angle (`PatternTextAngle`), needed
    only by that text branch; every other shape ignores them.
    """
    if part.shape == "text":
        return _pattern_text_ink(part, ox, oy, sin_t, cos_t, index, start, step,
                                 fonts_root).bounds()
    return part.ink(ox, oy, sin_t, cos_t)


def _pattern_steps(
    b: Builder, node: dict[str, Any], common: dict[str, Any], count: int,
) -> tuple[float, float, Position | None] | None:
    """A pattern's `step:`/`start:` as `(step_degrees, start_degrees,
    step_position)`, or `None` once an error is reported.  Radial: an
    angle step (default 360deg / count) that must neither be zero nor
    wrap a full turn, plus an optional start angle.  Linear: a required
    `{dx, dy}` step and no `start:`; both angles are 0.
    """
    element_id = common["id"]
    step_raw = node.get("step")
    if node["pattern"] != "radial":
        if "start" in node:
            b.bag.error(
                "pattern",
                f"{element_id}.start: not accepted on 'pattern: {node['pattern']}' -- "
                "only a radial pattern has a start copy angle",
                b.doc.span(node, "start"),
                notes=["'step: {dx, dy}' already places copy 0 relative to 'at:'"],
            )
            return None
        if step_raw is None:
            b.bag.error(
                "pattern",
                f"{element_id}.step: a {node['pattern']} pattern needs a "
                "'step: {dx, dy}' between copies",
                b.doc.span(node) or common["span"],
                notes=["radial's angle default (360deg / count) has no "
                       "equivalent -- there is no natural spacing to assume"],
            )
            return None
        if not isinstance(step_raw, dict):
            b.bag.error(
                "pattern",
                f"{element_id}.step: 'pattern: {node['pattern']}' takes {{dx, dy}} for "
                "'step:', not an angle",
                b.doc.span(node, "step"),
                notes=["an angle 'step:' is for 'pattern: radial'"],
            )
            return None
        return 0.0, 0.0, b.position(step_raw, node, "step")

    if isinstance(step_raw, dict):
        b.bag.error(
            "pattern",
            f"{element_id}.step: 'pattern: radial' takes an angle for "
            "'step:' (default 360deg / count), not {dx, dy}",
            b.doc.span(node, "step"),
            notes=["'{dx, dy}' is for 'pattern: linear' and 'pattern: grid'"],
        )
        return None
    if step_raw is None:
        step_degrees = 360.0 / count
    else:
        step_angle = b.angle(node, "step")
        if step_angle is None:
            return None  # angle already reported the real mistake
        step_degrees = step_angle.degrees
    start_angle = b.angle(node, "start") if "start" in node else None
    if "start" in node and start_angle is None:
        return None  # angle already reported the real mistake
    start_degrees = start_angle.degrees if start_angle is not None else 0.0

    if step_degrees == 0.0:
        b.bag.error(
            "pattern",
            f"{element_id}.step: 'step: 0deg' draws every copy on top "
            "of copy 0",
            b.doc.span(node, "step") or common["span"],
            notes=["a radial pattern's whole point is turning between "
                   "copies -- give it a nonzero step, or write one "
                   "element if a single copy is all you want"],
        )
        return None
    if count > 1:
        span = abs(step_degrees) * (count - 1)
        if span >= 360.0 - 1e-9:
            wrap_index = min(count - 1, math.ceil(360.0 / abs(step_degrees)))
            b.bag.error(
                "pattern",
                f"{element_id}: copies 0 and {wrap_index} land on the same "
                f"angle -- 'step:' x (count - 1) = {span:g}deg reaches a "
                "full turn",
                b.doc.span(node, "step") or common["span"],
                notes=[f"count: {count}, step: {step_degrees:g}deg -- "
                       "reduce count or step so the copies do not wrap "
                       "past 360deg"],
            )
            return None
    return step_degrees, start_degrees, None


def _render_pattern_texts(b: Builder, element_id: str, parts: list[AnyHandPart], count: int) -> bool:
    """Fill each `shape: text` part's per-copy strings (`TextPart.texts`),
    device-independently -- the same evaluation the host preview does
    for an ordinary `text` element, which is what makes a text part's
    font subset, measured extent and glyph lint exact.  Returns `False`
    if any part's copy fails to evaluate (each reported)."""
    ok = True
    for part in parts:
        if part.shape != "text":
            continue
        if part.text_literal is not None:
            part.texts = (part.text_literal,) * count
            continue
        texts: list[str] = []
        # A text part has `text:` or `value:`, never neither (PatternKind.build).
        assert part.text_value is not None and part.text_value.ast is not None
        for i in range(count):
            value = expr.evaluate(part.text_value.ast, {expr.COPY: i})
            if value is None:
                b.bag.error(
                    "pattern",
                    f"{element_id}: a pattern text part's value could "
                    f"not be evaluated for copy {i}",
                    part.text_value.span,
                    notes=["expected a copy-only expression to "
                           "evaluate for every copy index"],
                )
                ok = False
                break
            texts.append(formatting.render(
                part.format or "{}", value, part.text_value.value.type))
        else:
            part.texts = tuple(texts)
    return ok


def _check_pattern_absence(b: Builder, node: dict[str, Any], element: PatternElement) -> None:
    """One element-level `absent:` check for a pattern, in place of
    a per-colour refusal: a pattern colour may read a source that can be
    absent, so the compiler needs a policy from the author instead of a
    blanket rejection.

    Collects every nullable colour (the element's own `color:`, and
    each part's) and every nullable part `visible:` -- deliberately
    **not** the element's own `visible:`, which keeps its ordinary
    "absent means hidden, no policy" rule (`_visible`'s own docstring) --
    and reports **one** error naming every nullable source found, not
    one per expression, the same "one error, not N" discipline
    `docs/lore/codegen.md` asks for everywhere else.  The wording is the
    house `check_other_absence` style, adapted: a pattern has no
    `placeholder:`/`fallback:` to offer, only `hide`, and absence hides
    the *whole* pattern (every copy, every part), not just the one
    binding that went missing -- the reading is taken once per frame,
    before the loop.

    The mirror case -- `absent: hide` declared but nothing on the
    pattern is ever absent -- reuses `check_absence`'s own "has no
    effect" wording, so both notes read the same across every element
    kind that has one.

    Reads `element.bound_expressions()` by role rather
    than `element.colors`/`element.parts` directly -- `ROLE_COLOR` is
    every colour `.colors` already dedups, `ROLE_PART_VISIBLE` every
    part's own `visible:` -- so this is the same collection as before,
    just named by what each expression *is* instead of where it lives.
    """
    nullable: list[Expression] = []
    for role, expression in element.bound_expressions():
        if role in (ROLE_COLOR, ROLE_PART_VISIBLE) \
                and expression.nullable and expression not in nullable:
            nullable.append(expression)

    if nullable:
        if element.absent is not None:
            return
        sources = tuple(sorted(b.nullable_sources(tuple(nullable))))
        first = nullable[0]
        b.bag.error(
            "when-absent",
            f"{element.id}: reads {and_paths(sources)}, which can be "
            "absent, so 'absent: hide' is required",
            first.span,
            notes=[
                ABSENCE_IS_NORMAL,
                "a pattern has no text or value to use instead -- absence hides "
                "the whole pattern, every copy and every part, because the "
                "reading is taken once per frame, before the loop",
                "add 'absent: hide' to the pattern",
            ],
        )
        return
    if element.absent is not None:
        b.bag.note(
            "when-absent",
            f"{element.id}: 'absent:' has no effect -- nothing this "
            "pattern reads is ever absent",
            b.doc.span(node, "absent"),
        )


def _pattern_needs_math(placed: PlacedPattern) -> bool:
    """Does this pattern's device loop compute a `sin`/`cos` pair at all?

    Only a **radial** pattern turns, and even one skips it when every part
    is an `arc`: an arc's start angle turns by plain degree subtraction
    (`WfbArc.drawSpan`'s `startDegrees`), not by rotating a coordinate.
    Every other part -- a text part's anchor included (`WfbGeom.rotatedX`/
    `rotatedY`) -- takes `sin`/`cos`.  Shared by the view's import gate and
    `PatternKind.lower` so the two cannot disagree about whether the loop
    declares `angle`/`sin`/`cos`.
    """
    if placed.element.pattern != "radial":
        return False
    return any(part.shape != "arc" for part in placed.parts)


def _pattern_skip_terms(element: PatternElement) -> list[Cond]:
    """The loop's skip test, in one fixed order: `skip_every:` first, then
    every explicit `skip:` index it does not already cover (an index
    `skip_every:` already catches would test true a second time for no
    reason).  Empty when nothing is skipped, and the loop then has no
    `if` at all."""
    i = NumLocal("i")
    terms: list[Cond] = []
    if element.skip_every is not None:
        terms.append(Cmp("==", Bin("%", i, Lit(element.skip_every)), Lit(0)))
    for index in element.skip:
        if element.skip_every is None or index % element.skip_every != 0:
            terms.append(Cmp("==", i, Lit(index)))
    return terms


def _pattern_angle(element: PatternElement) -> tuple[Num, str]:
    """The radial loop's `angle` (radians, bare `Float` literals) and the
    degrees comment beside it: `<start> + i * <step>`, the start term left
    out of the code at `start: 0deg` (the common case); the comment always
    spells out both numbers."""
    i = NumLocal("i")
    step = Bin("*", i, FloatLit(math.radians(element.step_angle)))
    comment = f"({element.start_angle:g} + {element.step_angle:g} i) degrees"
    if element.start_angle == 0.0:
        return step, comment
    return Bin("+", FloatLit(math.radians(element.start_angle)), step), comment


def _lower_part(element: PatternElement, placed: PlacedPattern, prefix: str, index: int,
                part: ResolvedHandPart, radial: bool, hoist_pen: bool, text_fonts: dict[str, str],
                pen: AodPick, stamp: tuple[Paint, int] | None, ring: int | None) -> list[Op]:
    """One template part, drawn for the current copy `i`: polygon, line and
    circle parts through the barrel (`Part`: rotated for a radial pattern,
    translated otherwise, as a hand's parts are).  An `arc` part always goes
    through `WfbArc.drawSpan`, its start angle turned by plain degree
    subtraction.  A `text` part moves only its anchor (`WfbGeom.rotatedX`/
    `rotatedY`, or `ox + ...`), unless its own `curve:` turns the glyphs too
    (`_lower_text_part`).  With ``ring`` (the pattern's `outline:`, its
    colour already set), only the part's ring is drawn."""
    part_prefix = f"{prefix}_{index}"
    if part.shape == "text":
        return _lower_text_part(element, part, part_prefix, index, radial, text_fonts, stamp,
                                ring)
    if part.shape != "arc":
        return [Part(part, part_prefix, radial, pen, set_pen=not hoist_pen, ring=ring)]
    # arc: always centred on the copy's own origin.  A radial pattern turns
    # the author start angle by plain degree subtraction -- the arithmetic
    # `wfb.layout.garmin_arc` performs at build time for a standalone `shape:
    # arc`, with `i * step` folded in at runtime -- so copy 0 reaches
    # `WfbArc.drawSpan` with exactly the numbers a `shape: arc` of the same
    # angles would.  A linear pattern never turns, so only its centre moves.
    g0 = FloatLit(90.0 - (part.start_angle + element.start_angle))
    start: Num = (Bin("-", g0, Bin("*", NumLocal("i"), FloatLit(element.step_angle)))
                  if radial else g0)
    cx, cy = (NumLocal("cx"), NumLocal("cy")) if radial else (NumLocal("ox"), NumLocal("oy"))
    radius = Const(f"{part_prefix}_RADIUS", part.radius)
    offsets = disc_perimeter_offsets(ring) if ring is not None else ((0, 0),)
    return [ArcSpan(Shifted(cx, dx), Shifted(cy, dy), radius, pen, start, FloatLit(part.sweep),
                    pen_first=True)
            for dx, dy in offsets]


def _text_angle(element: PatternElement, part: ResolvedTextPart) -> Num:
    """The per-copy Garmin-degrees angle a `shape: text` part's own `curve:`
    draws at: the part's own local, copy-0 angle (`part.curve.angle_garmin`)
    composed with the copy's rotation, `g0 - i * step_deg` with
    `element.start_angle` folded into `g0` -- the same shape an `arc` part's
    start angle gets (`_lower_part`).  A clockwise design-degree rotation is a
    plain Garmin-degree subtraction whichever `curve.style` produced the
    local angle; a linear pattern's start/step are `0.0`, leaving the local
    angle unchanged on every copy.  `local`/`start`/`step` are the terms
    `PatternTextAngle` gives the lint ink.  Full derivation:
    `docs/lore/codegen.md` ("Vector fonts and `curve:` on a pattern's own
    `shape: text` part")."""
    radial = element.pattern == "radial"
    terms = PatternTextAngle(part.curve.angle_garmin, element.start_angle,
                             element.step_angle if radial else 0.0)
    g0 = FloatLit(terms.local - terms.start)
    return Bin("-", g0, Bin("*", NumLocal("i"), FloatLit(terms.step))) if radial else g0


def _lower_text_part(element: PatternElement, part: ResolvedTextPart, part_prefix: str,
                     index: int, radial: bool, text_fonts: dict[str, str],
                     stamp: tuple[Paint, int] | None, ring: int | None) -> list[Op]:
    """One copy's `shape: text` part -- or with ``ring``, only its ring
    stamped in the pattern's ring colour: ahead of the interior, inside the
    same vector-font null guard, the part's own `outline:` stamp, then the
    interior call.

    **Gate 4 is never omitted, on any device, in either `unsupported:`
    mode** (`docs/research/12-vector-fonts.md` §1): a vector font's draw is
    wrapped `if (<font local> != null)` whether or not it is curved, since
    `Graphics.getVectorFont` can return null even when every build-time
    gate passed.  The local was loaded once before the copy loop.  A baked
    font never reaches this guard: its pre-loop load returns on null
    instead.

    **The ring colour and its restore are local to this part**: the
    sequence always leaves `dc`'s colour at the part's own (restyled for
    the AOD frame), exactly what the copy loop already believes is current.
    The ring takes no `aod:` override key; it is only dimmed."""
    ir_part = element.parts[index]
    assert ir_part.shape == "text"  # resolved parts are the IR parts, 1:1
    printed: Str
    if ir_part.text_literal is not None:
        printed = StrLit(ir_part.text_literal.replace("\\", "\\\\").replace('"', '\\"'))
    else:
        assert ir_part.text_value is not None  # `text:` or `value:`, never neither
        printed = Reading(ir_part.format or "{}", ir_part.text_value)
    text = PerCopy(printed, part.texts)
    font_code = (text_fonts[part.font.reference] if part.font.is_custom
                 else f"Graphics.{part.font.reference}")
    vector = part.font.is_vector
    font = Font(font_code, baked=part.font.reference if part.font.is_custom and not vector
                else None, metric=part.font.metric, vector=vector)
    style = part.curve.style
    px, py = Const(f"{part_prefix}_X", part.x), Const(f"{part_prefix}_Y", part.y)
    if radial:
        # `bottom` drops the shared `cy` translation term only for this
        # call; the subtraction lands outside the rotation, so it moves the
        # drawn point straight up on screen whatever the angle.  `curve:`
        # has no `bottom` (`Builder.build_curve`).
        rotate = (NumLocal("cx"), NumLocal("sin"), NumLocal("cos"))
        cy: Num = (NumLocal("cy") if style is not None
                   else FontDrop(NumLocal("cy"), part.vertical_align, font_code))
        x: Num = Call("WfbGeom.rotatedX", (px, py, *rotate))
        y: Num = Call("WfbGeom.rotatedY", (px, py, cy, NumLocal("sin"), NumLocal("cos")))
    else:
        x = Bin("+", NumLocal("ox"), px)
        oy = Bin("+", NumLocal("oy"), py)
        y = oy if style is not None else FontDrop(oy, part.vertical_align, font_code)
    angle = _text_angle(element, part) if style is not None else None

    def call(dx: int = 0, dy: int = 0) -> Text:
        return Text(Shifted(x, dx), Shifted(y, dy), font, text, tuple(part.justify),
                    part.vertical_align, align=part.align, style=style, angle=angle,
                    radius=(Const(f"{part_prefix}_RADIUS", part.curve.radius_px)
                            if style == "radial" else None),
                    direction=part.curve.direction, shift_y=False,
                    split_x=radial or style is not None)

    body: list[Op]
    if ring is not None:
        assert stamp is not None
        body = [SetColor(stamp[0]), *(call(dx, dy) for dx, dy in disc_perimeter_offsets(ring))]
    else:
        body = []
        if part.outline_color is not None:
            body += [SetColor(AodDimmed(element, part.outline_color)),
                     *(call(dx, dy) for dx, dy in disc_perimeter_offsets(part.outline_width)),
                     Blank(), SetColor(AodPart(element, part.color))]
        body.append(call())
    if vector:
        return [IfNotNull(font_code, tuple(body), present=part.font.available)]
    return body


class PatternKind(ElementKind[PatternElement, PlacedPattern]):
    name = "pattern"
    ir_class = PatternElement
    placed_class = PlacedPattern
    antialiased = True
    ringed = True

    def ring_refusal(self, element: PatternElement) -> str | None:
        if any(part.shape == "text" and part.outline is not None for part in element.parts):
            return ("round a pattern with a ringed text part is not implemented yet: "
                    "drop the part's own 'outline:' or the pattern's")
        return None

    def build(self, b: Builder, node: dict[str, Any], common: dict[str, Any], path: tuple[str | int, ...]) -> Element | None:
        """`type: pattern` -- one template, drawn `count:` times, turned
        about `at:` (`pattern: radial`), stepped along `{dx, dy}`
        (`pattern: linear`), or stepped in rows of `columns:`
        (`pattern: grid`).

        Every check is a build-time error, and each returns `None` on its
        own violation rather than falling through to the next, so a design
        with exactly one mistake gets exactly one error ("one error, not
        N", `docs/lore/codegen.md`).
        """
        element_id = common["id"]
        count = node["count"]

        if "low_power" in common["modes"]:
            b.bag.error(
                "pattern",
                f"{element_id}: 'sleep_update: true' is not accepted on a pattern",
                b.doc.span(node, "sleep_update") or common["span"],
                notes=["a fixed pattern gains nothing from onPartialUpdate -- its "
                       "geometry never changes -- and its clip would be its whole "
                       "extent"],
            )
            return None

        steps = _pattern_steps(b, node, common, count)
        if steps is None:
            return None
        columns = node.get("columns")
        if node["pattern"] == "grid" and columns is None:
            b.bag.error("pattern", f"{element_id}: 'pattern: grid' needs 'columns:' -- "
                        "how many copies per row", b.doc.span(node, "pattern"),
                        notes=["'count:' is the total, so the last row may be partial"])
            return None
        if node["pattern"] != "grid" and columns is not None:
            b.bag.error("pattern", f"{element_id}.columns: read only by 'pattern: grid'",
                        b.doc.span(node, "columns"))
            return None
        step_degrees, start_degrees, step_position = steps

        skip = tuple(sorted({int(i) for i in (node.get("skip") or [])}))
        out_of_range = [i for i in skip if i >= count]
        if out_of_range:
            b.bag.error(
                "pattern",
                f"{element_id}.skip: index" + ("es" if len(out_of_range) > 1 else "")
                + f" {', '.join(str(i) for i in out_of_range)} out of range for "
                f"'count: {count}' (0..{count - 1})",
                b.doc.span(node, "skip"),
            )
            return None
        skip_every = node.get("skip_every")
        if skip_every is not None and skip_every > count:
            b.bag.error(
                "pattern",
                f"{element_id}.skip_every: {skip_every} is greater than "
                f"'count: {count}', so it skips nothing",
                b.doc.span(node, "skip_every"),
            )
            return None
        if not drawn_copies(count, skip, skip_every):
            b.bag.error(
                "pattern",
                f"{element_id}: 'skip:'/'skip_every:' leave every copy undrawn",
                b.doc.span(node, "skip_every") or b.doc.span(node, "skip")
                or common["span"],
                notes=["remove the element, or skip fewer copies"],
            )
            return None

        parts: list[AnyHandPart] = []
        # `copy` -- the index of the copy being drawn -- exists only here,
        # compiled to the generated loop's own index (`PatternKind.lower`).
        b.scope.define(expr.COPY, expr.Binding(expr.Value(Type.NUMBER), code=PATTERN_LOOP_INDEX))
        try:
            # Any source is allowed here, absent-able or not:
            # `_check_pattern_absence` polices absence for the whole element.
            element_color, color_failed = b.owned_color(node, element_id, hand=False)
            ok = not color_failed
            for index, raw_part in enumerate(node.get("parts") or []):
                part = b.build_hand_part(
                    raw_part, element_id, index, element_color, color_failed,
                    context="pattern",
                )
                if part is None:
                    ok = False
                    continue
                parts.append(part)
        finally:
            del b.scope.bindings[expr.COPY]

        if not ok or not _render_pattern_texts(b, element_id, parts, count):
            return None

        colors: list[Expression] = []
        dedup_append(colors, element_color)
        for part in parts:
            dedup_append(colors, part.color)
            if part.shape == "text" and part.outline is not None:
                dedup_append(colors, part.outline.color)

        element = PatternElement(
            **common,
            pattern=node["pattern"],
            count=count,
            step_angle=step_degrees,
            start_angle=start_degrees,
            step=step_position,
            columns=columns,
            skip=skip,
            skip_every=skip_every,
            parts=parts,
            color=element_color,
            colors=tuple(colors),
            absent=node.get("absent"),
        )
        _check_pattern_absence(b, node, element)
        return element

    def resolve(self, r: Resolver, element: PatternElement, parent: Box, depth: int) -> Placed:
        """`type: pattern` -- the template resolved once in its own frame
        (`resolve_parts`, as for a hand), plus which copies are drawn and
        the repeat rule; the device performs the repeat transform itself
        (ADR 0004, amended).

        A radial pattern's `reach` is rotation-invariant for every shape but
        text, so it comes from the per-part reach.  Upright glyphs are not
        (a text part's own reach is `0.0`), so each *drawn* copy's real text
        ink (`_pattern_text_ink`) is measured in the per-copy loop that also
        unions `box` from every drawn copy's ink.
        """
        cx, cy = r.point(element.at, parent)
        center = (round(cx), round(cy))

        parts, reach = r.resolve_parts(
            element.parts, element.id, min_1px=element.resolved_min_1px)

        if element.pattern == "radial":
            start, step = element.start_angle, element.step_angle
            dx = dy = 0
        else:
            start = step = 0.0
            reach = 0.0  # only a radial pattern reports a disc
            step_position = element.step or Position()
            dx = round_half_away(r.length(step_position.dx, parent, Axis.X, 0))
            dy = round_half_away(r.length(step_position.dy, parent, Axis.Y, 0))

        aod_thickness = r.aod_extent(element, "thickness", parent, 1)
        placed = PlacedPattern(
            element, IntBox(0, 0, 0, 0), center, depth,
            parts=parts, copies=element.drawn_indices(),
            start=start, step=step, dx=dx, dy=dy, columns=element.columns or 0, reach=reach,
            aod_thickness=aod_thickness,
        )

        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        text_reach = 0.0
        cx_f, cy_f = float(center[0]), float(center[1])
        for index in placed.copies:
            ox, oy, sin_t, cos_t = placed.transform(index)
            for part in parts:
                if part.shape == "text":
                    # `start`/`step` are this pattern's own repeat angle
                    # (`0.0`/`0.0` for a linear pattern) -- only a curved
                    # text part composes with it (`PatternTextAngle`).
                    ink = _pattern_text_ink(part, ox, oy, sin_t, cos_t, index, start, step,
                                            r.device.fonts_root)
                    lo_x, lo_y, hi_x, hi_y = ink.bounds()
                    if element.pattern == "radial":
                        # The real ink's farthest point, not its AABB's
                        # corners -- those overreach, and used to make a
                        # full ring of curved numerals trip `safe-area`.
                        text_reach = max(text_reach, ink.reach(cx_f, cy_f))
                else:
                    lo_x, lo_y, hi_x, hi_y = _pattern_part_ink(part, ox, oy, sin_t, cos_t, index)
                min_x, min_y = min(min_x, lo_x), min(min_y, lo_y)
                max_x, max_y = max(max_x, hi_x), max(max_y, hi_y)
        if min_x > max_x:
            # Unreachable once the schema and `wfb.ir` have run (`parts:`
            # needs at least one entry, and every copy skipped is a build
            # error) -- kept so a malformed element resolves to something
            # rather than crash.
            box = Box(cx, cy, 0, 0)
        else:
            box = Box(min_x, min_y, max_x - min_x, max_y - min_y)
        placed.box = box.rounded()
        if text_reach > placed.reach:
            placed.reach = text_reach
        return placed

    def aod_refusal(self, key: str, shape: str | None,
                    literal_text: bool) -> tuple[str, str, list[str]] | None:
        if key == "font":
            return (
                "aod",
                "a pattern's 'aod: {font: ...}' override is not implemented yet",
                ["restyle this pattern's colour/thickness in AOD instead, or drop the font "
                 "override for now"],
            )
        return None

    def circular_extent(self, placed: PlacedPattern) -> tuple[float, float, float] | None:
        if placed.element.pattern == "radial":
            return (placed.center[0], placed.center[1], placed.reach)
        return None

    def text_runs(self, element: PatternElement, face: Face) -> list[TextRun]:
        # Every drawn copy's string is known at build time (`TextPart.texts`),
        # so a text part's font needs exactly those, and is checked on each.
        drawn = element.drawn_indices()
        runs = []
        for index, part in enumerate(element.parts):
            if part.shape != "text" or not part.font_is_custom:
                continue
            samples = tuple(part.texts[copy_index] for copy_index in drawn)
            runs.append(TextRun(
                f"{element.id}.parts[{index}]", part.font, glyphs=frozenset("".join(samples)),
                samples=samples, part_index=index, span=part.span,
                unsupported=part.unsupported, curve=part.curve))
        return runs

    def lower(self, ctx: DrawContext, placed: PlacedPattern) -> list[Op]:
        """`type: pattern` -- loop over the drawn copies, turning (radial) or
        translating (linear, grid) the template resolved once at build time.
        The same bargain `wfb.kinds.hands.HandsKind` strikes for analog
        hands: the device performs the one piece of layout arithmetic ADR
        0004 leaves it (a rotation or a translation), everything else is a
        `Layout` constant.

        Per-copy part `visible:`: a part whose `visible:` folded to a
        compile-time `false` is dropped entirely -- no colour, no draw call --
        the `dead-element` lint already told the author.  A part whose
        `visible:` is not constant is *gated*: its own drawing (pen included)
        sits inside `if (<condition>) { ... }`, but its `dc.setColor(...)`
        stays before the gate, unconditional, so the pen colour after this
        part is the same whichever branch ran, and the part after it never
        has to ask whether this one drew.

        A `text` part's custom font is loaded into a local **once, before the
        loop**, the same "load once, guard once" rule `wfb.kinds.text.
        TextKind.lower` follows, hoisted since every copy shares one font.
        Two parts naming different fonts get two locals (``font0``,
        ``font1``, ...); two naming the same font share one load and one
        guard.  **A `face:` (vector) font is the exception**: it is loaded
        once but never early-return-guarded, because it can be null on the
        ordinary "this device does not have it" path, and an early `return;`
        would cancel every *other* part of this pattern too.  Its draw is
        wrapped in `if (<local> != null)` instead, once per copy.

        Colour: one distinct part colour is set once, before the loop;
        several are set inside it, only on each change.  A colour that reads
        `copy` is the loop's own `i`, so it is never hoisted.  `outline:`
        rings each copy whole just before its parts, setting the ring colour
        every copy, so nothing is hoisted then either.  The pen width is
        hoisted when every line and outlined circle shares one width and
        there is no arc part: `WfbArc.drawSpan` resets the pen to 1 itself.

        With `ctx.ring` (an outlined group's pass), only the rings are
        drawn."""
        element = placed.element
        aod = ctx.aod
        prefix = const_prefix(placed.id)
        override = (Const(f"{prefix}_AOD_THICKNESS", placed.aod_thickness)
                    if placed.aod_thickness is not None else None)
        live = [
            (index, part) for index, part in enumerate(placed.parts)
            if not ((visible := element.parts[index].visible) is not None
                    and visible.is_constant)
        ]
        radial = element.pattern == "radial"
        i = NumLocal("i")
        ops: list[Op] = []
        if radial:
            ops += [Let("cx", Const(f"{prefix}_X", placed.center[0])),
                    Let("cy", Const(f"{prefix}_Y", placed.center[1]))]

        text_fonts: dict[str, str] = {}
        vector_text_fonts: set[str] = set()
        for _, part in live:
            if (part.shape == "text" and part.font.is_custom
                    and part.font.reference not in text_fonts):
                text_fonts[part.font.reference] = f"font{len(text_fonts)}"
                if part.font.is_vector:
                    vector_text_fonts.add(part.font.reference)
        for reference, local in text_fonts.items():
            ops += [LoadFont(local, f"_{font_field(reference)}",
                             on_null="none" if reference in vector_text_fonts else "return"),
                    Blank()]

        paints = [AodPart(element, part.color) for _, part in live]
        codes = [color_code(paint, aod) for paint in paints]
        distinct = list(dict.fromkeys(codes))
        per_copy = any(expr.reads_copy(part.color.ast) for _, part in live
                       if part.color is not None)
        stamp: tuple[Paint, int] | None = None
        if ctx.ring is not None:
            stamp = (RingColor(), ctx.ring.width)
        elif element.outline is not None:
            stamp = (AodDimmed(element, element.outline.color), element.outline.width)
        hoist_color = len(distinct) == 1 and not per_copy and stamp is None
        pen_parts = [(index, part) for index, part in live
                     if part.shape == "line" or (part.shape == "circle" and not part.filled)]
        has_arc = any(part.shape == "arc" for _, part in live)
        hoist_pen = (bool(pen_parts) and not has_arc
                     and len({p.thickness for _, p in pen_parts}) == 1)

        def pen(index: int, part: ResolvedHandPart) -> AodPick:
            return AodPick(Const(f"{prefix}_{index}_THICKNESS", getattr(part, "thickness", 1)),
                           override)

        if hoist_color:
            ops.append(SetColor(paints[0], note="hoisted: one colour"))
        if hoist_pen:
            ops.append(SetPen(pen(*pen_parts[0]), note="hoisted: one pen, no arc"))

        body: list[Op] = []
        skip = _pattern_skip_terms(element)
        if skip:
            body.append(If(AnyOf(tuple(skip)), (Continue(),)))
        if radial:
            if _pattern_needs_math(placed):
                angle, note = _pattern_angle(element)
                body += [Let("angle", angle, note=note),
                         Let("sin", Call("Math.sin", (NumLocal("angle"),))),
                         Let("cos", Call("Math.cos", (NumLocal("angle"),)))]
        else:
            x0 = Const(f"{prefix}_X", placed.center[0])
            y0 = Const(f"{prefix}_Y", placed.center[1])
            dx = Const(f"{prefix}_DX", placed.dx)
            dy = Const(f"{prefix}_DY", placed.dy)
            if element.pattern == "grid":
                # Number / Number is integer division in Monkey C: the row.
                assert element.columns is not None
                columns = Lit(element.columns)
                body += [Let("ox", Bin("+", x0, Bin("*", Paren(Bin("%", i, columns)), dx))),
                         Let("oy", Bin("+", y0, Bin("*", Paren(Bin("/", i, columns)), dy)))]
            else:
                body += [Let("ox", Bin("+", x0, Bin("*", i, dx))),
                         Let("oy", Bin("+", y0, Bin("*", i, dy)))]

        def parts(ring: int | None) -> list[Op]:
            out: list[Op] = []
            current = codes[0] if hoist_color else None
            for paint, code, (index, part) in zip(paints, codes, live):
                if ring is None and not hoist_color and code != current:
                    out.append(SetColor(paint))
                    current = code
                drawn = _lower_part(element, placed, prefix, index, part, radial, hoist_pen,
                                    text_fonts, pen(index, part), stamp, ring)
                visible = element.parts[index].visible
                if visible is not None:
                    # Non-constant, or `live` would have excluded it above.
                    out += [Comment(f"visible: {visible.text}"), If(Truthy(visible), tuple(drawn))]
                else:
                    out += drawn
            return out

        if stamp is not None:
            # This copy ringed whole: every part's ring, then the parts.
            body += [SetColor(stamp[0]), *parts(stamp[1])]
        if ctx.ring is None:
            body += parts(None)
        ops.append(For("i", Lit(element.count), tuple(body), copy=True))
        if hoist_pen:
            ops.append(SetPen(None))
        return ops

    def describe(self, placed: PlacedPattern) -> str:
        element = placed.element
        total = element.count
        drawn_count = len(placed.copies)
        note = "" if drawn_count == total else f" ({drawn_count} drawn)"
        if element.pattern == "radial":
            return f"a radial pattern: {total} copies, {element.step_angle:g} degrees apart{note}"
        step = element.step or Position()
        offsets = [f"{axis} {length}" for axis, length in
                  (("dx", step.dx), ("dy", step.dy)) if length is not None]
        step_desc = ", ".join(offsets) if offsets else "0px"
        if element.pattern == "grid":
            return (f"a grid pattern: {total} copies in rows of {element.columns}, "
                    f"step {step_desc}{note}")
        return f"a linear pattern: {total} copies, step {step_desc}{note}"

    def layout_constants(self, prefix: str,
                         placed: PlacedPattern) -> "layout_constants_mod.Constants":
        radial = placed.element.pattern == "radial"
        out: "layout_constants_mod.Constants" = [
            (f"{prefix}_X", placed.center[0],
             "the centre every copy turns about" if radial else "copy 0's origin"),
            (f"{prefix}_Y", placed.center[1], ""),
        ]
        if not radial:
            out.append((f"{prefix}_DX", placed.dx,
                        "step between columns, whole pixels" if placed.element.pattern == "grid"
                        else "step between copies, whole pixels"))
            out.append((f"{prefix}_DY", placed.dy, ""))
        out.extend(layout_constants_mod.aod_thickness_constant(
            prefix, placed, layout_constants_mod.EVERY_PART_NOTE))
        for index, part in enumerate(placed.parts):
            out.extend(layout_constants_mod.hand_part_constants(
                f"{prefix}_{index}", "template", index, part))
        return out

    def contrast_subjects(self, placed: PlacedPattern) -> Iterator[ContrastSubject]:
        """A `pattern` yields each template part once (every copy shares its
        colours); it has no per-part structure on `Element.color_roles()`
        either.  `allow_backdrop_match` is false only for a `shape: text` part,
        the one shape where an exact backdrop match is invisible content by
        mistake."""
        ring = placed.element.outline.color if placed.element.outline is not None else None
        for index, part in enumerate(placed.parts):
            outline_color = part.outline_color if part.shape == "text" else None
            yield (f"{placed.id}.parts[{index}]", part.color, outline_color or ring,
                   part.shape != "text")


KIND = PatternKind()
