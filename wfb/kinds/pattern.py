"""`type: pattern` -- one template of 1-16 primitives, drawn repeatedly:
turned about `at:` (`pattern: radial`), stepped along `{dx, dy}`
(`pattern: linear`), or stepped in rows of `columns:` (`pattern: grid`)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import math
from dataclasses import dataclass

from .. import catalog, expr, formatting
from ..catalog import Type
from ..fonts import BakedFont
from ..ir.builder import ABSENCE_IS_NORMAL, and_paths, dedup_append
from ..ir.model import (
    AnyHandPart, Element, Expression, PATTERN_LOOP_INDEX, PatternElement, Position,
    ROLE_COLOR, ROLE_PART_VISIBLE, drawn_copies,
)
from ..layout import (
    Ink, Placed, PlacedPattern, ResolvedArcPart, ResolvedHandPart, ResolvedTextPart,
    round_half_away, text_ink,
)
from ..preview import arc_span
from ..units import Axis, Box, IntBox
from ..emit.monkeyc import layout_constants as layout_constants_mod
from ..emit.monkeyc import rotated
from ..emit.monkeyc.common import (
    NO_AOD, AodStyle, const_prefix, font_field, glyph_y_expr, mc_float,
)
from ..emit.monkeyc.shapes import RADIAL_DIRECTION, emit_outline_loop, radial_radius_expr
from ..emit.writer import Writer
from . import ElementKind, TextRun

if TYPE_CHECKING:
    from collections.abc import Iterator

    from . import ContrastSubject
    from ..ir.builder import Builder
    from ..ir.model import Face
    from ..emit.monkeyc.readplan import ReadPlan
    from ..layout import ResolvedFace, Resolver
    from ..preview import Renderer


@dataclass(frozen=True)
class PatternTextAngle:
    """The terms of the per-copy Garmin-degrees angle a `shape: text`
    pattern part's own `curve:` draws at (plan 11 slice 2, plan 19 A1):
    `local` -- the part's own local, copy-0 angle (`part.curve.angle_garmin`);
    `start`/`step` -- the pattern's own repeat angle, design degrees
    clockwise from 12 (`0.0`/`0.0` for a linear pattern, which then leaves
    every copy at the local angle unchanged).  One definition of the
    composition, shared by the lint ink (`_pattern_text_ink`), the preview
    (`_pattern_text`, via :meth:`copy_curve_angle`) and codegen
    (`_emit_pattern_text_angle_expr`, which reads
    `local`/`start`/`step` off this same object but builds its own Monkey C
    from them -- `start` folded into a build-time literal with `local`,
    `step` multiplied by the runtime copy index -- rather than calling
    :meth:`copy_curve_angle`, since one runs at build time and the other
    on-device).
    """

    local: float
    start: float
    step: float

    def copy_curve_angle(self, index: int) -> float:
        """`(local - (start + index * step)) % 360.0` -- today's exact
        expression order, kept so a lint box or a preview pixel never
        moves."""
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
    `_emit_pattern_text_angle_expr` emits.
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
    """One element-level `when_absent:` check for a pattern, in place of
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

    The mirror case -- `when_absent: hide` declared but nothing on the
    pattern is ever absent -- reuses `check_absence`'s own "has no
    effect" wording, so both notes read the same across every element
    kind that has one.

    Reads `element.bound_expressions()` by role (plan 19 A2) rather
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
        if element.when_absent is not None:
            return
        sources = tuple(sorted(b.nullable_sources(tuple(nullable))))
        first = nullable[0]
        b.bag.error(
            "when-absent",
            f"{element.id}: reads {and_paths(sources)}, which can be "
            "absent, so 'when_absent: hide' is required",
            first.span,
            notes=[
                ABSENCE_IS_NORMAL,
                "a pattern has no placeholder or fallback -- absence hides "
                "the whole pattern, every copy and every part, because the "
                "reading is taken once per frame, before the loop",
                "add 'when_absent: hide' to the pattern",
            ],
        )
        return
    if element.when_absent is not None:
        b.bag.note(
            "when-absent",
            f"{element.id}: 'when_absent' has no effect -- nothing this "
            "pattern reads is ever absent",
            b.doc.span(node, "when_absent"),
        )


def _pattern_absent(renderer: Renderer, element: PatternElement) -> bool:
    """Whether any nullable source this pattern's colours
    (`element.colors`: the default plus every part's own) or any part's
    own `visible:` reads is absent in the sample -- the host mirror of
    the null guard the device emits before its copy loop
    (`emit_draw`, fed by the same
    expressions). The element's own `visible:` is a separate axis
    (`render_element`).
    """
    sources: set[str] = set()
    for expression in element.colors:
        sources.update(expression.sources)
    for part in element.parts:
        if part.visible is not None:
            sources.update(part.visible.sources)
    return any(
        catalog.CATALOG[path].guard_needed and renderer.values.get(path) is None
        for path in sources
    )


def _pattern_arc(renderer: Renderer, placed: PlacedPattern, part: ResolvedArcPart, ox: float, oy: float, index: int,
                 values: dict[str, object]) -> None:
    """An `arc` template part -- always centred on the copy's own origin
    (`at:` is rejected on it), so only its *start angle* turns with the
    copy, as `WfbArc.drawSpan` is called on the device: `part.start_angle
    + start + index * step` (plain `part.start_angle` for a linear
    pattern, whose `start`/`step` are `0`)."""
    s = renderer.scale
    fill = renderer.aod_color(placed.element, "color", part.color, values)
    thickness = renderer.aod_geometry(placed, "thickness", part.thickness)
    cx, cy = ox * s, oy * s
    r = part.radius * s
    author_start = part.start_angle + placed.start + index * placed.step
    span = arc_span(author_start, part.sweep)
    if r > 0 and span is not None:
        renderer.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
                          fill=fill, width=max(1, thickness * s))


def _pattern_text(renderer: Renderer, placed: PlacedPattern, part: ResolvedTextPart, ox: float, oy: float,
                  sin_t: float, cos_t: float, index: int, values: dict[str, object]) -> None:
    """A `shape: text` template part, drawn at this copy's own anchor,
    rounded half-up the way `runtime-lib/WfbGeom.mc`'s `rotatedX`/
    `rotatedY` round it (:func:`pattern_text_anchor`), through the same
    `draw_text`/`draw_vector_text` a `text` element uses.

    A baked/system font draws upright glyphs. A `face:` font's `curve:`
    turns them, at the part's own local angle composed with this copy's
    rotation (:class:`PatternTextAngle`), the composition
    codegen (`_emit_pattern_text_angle_expr`) and the lint box
    (`_pattern_text_ink`) also perform. `outline:` stamps the
    already-transformed anchor, so the ring is a screen-space translation
    at every copy.
    """
    text = part.texts[index]
    color = renderer.aod_color(placed.element, "color", part.color, values)
    anchor = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
    ring_color = (
        renderer.aod_dimmed(placed.element, part.outline_color, values)
        if part.outline_color is not None else None
    )
    if part.font.is_vector:
        if not part.font.available:
            return  # `if_unavailable: hide` on this device
        angle = (
            PatternTextAngle(part.curve.angle_garmin, placed.start, placed.step)
            .copy_curve_angle(index) if part.curve.style is not None else 0.0
        )

        def draw(at: tuple[int, int], fill: tuple[int, int, int], box: IntBox | None = None) -> None:
            renderer.draw_vector_text(
                text, at, part.align, part.vertical_align, part.font.metric, fill,
                part.curve.style, angle, part.curve.radius_px, part.curve.direction)
    else:
        font: BakedFont | None = (
            renderer.resolved.fonts.get(part.font.reference) if part.font.is_custom else None
        )

        def draw(at: tuple[int, int], fill: tuple[int, int, int], box: IntBox | None = None) -> None:
            renderer.draw_text(font, text, at, part.align, part.vertical_align,
                               part.font.metric, fill)
    renderer.draw_outlined(draw, anchor, color, ring_color, part.outline_width)


def _pattern_needs_math(placed: PlacedPattern) -> bool:
    """Does this pattern's device loop compute a `sin`/`cos` pair at all?

    Only a **radial** pattern turns, and even one skips it when every part
    is an `arc`: an arc's start angle turns by plain degree subtraction
    (`WfbArc.drawSpan`'s `startDegrees`), not by rotating a coordinate.
    Every other part -- a text part's anchor included (`WfbGeom.rotatedX`/
    `rotatedY`) -- takes `sin`/`cos`.  Shared by the view's import gate and
    :func:`emit_draw` so the two cannot disagree about whether the loop
    declares `angle`/`sin`/`cos`.
    """
    if placed.element.pattern != "radial":
        return False
    return any(part.shape != "arc" for part in placed.parts)


def _pattern_skip_condition(element: PatternElement) -> str:
    """The loop's skip test, in one fixed order: `skip_every:` first, then
    every explicit `skip:` index it does not already cover -- an index
    `skip_every:` already catches would otherwise test true a second time
    for no reason.  Empty when nothing is skipped, which is what lets
    :func:`emit_draw` omit the `if` entirely.
    """
    terms: list[str] = []
    if element.skip_every is not None:
        terms.append(f"i % {element.skip_every} == 0")
    for index in element.skip:
        if element.skip_every is None or index % element.skip_every != 0:
            terms.append(f"i == {index}")
    return " || ".join(terms)


def _pattern_angle_expr(element: PatternElement) -> tuple[str, str]:
    """The radial loop's `angle` expression (radians, bare `Float`
    literals) and the degrees comment beside it: `<start> + i * <step>`,
    with the start term dropped from the *code* when `start: 0deg` (the
    common case) -- the comment always spells out both numbers, so the
    general rule stays visible even then.
    """
    step_rad = mc_float(math.radians(element.step_angle))
    comment = f"({element.start_angle:g} + {element.step_angle:g} i) degrees"
    if element.start_angle == 0.0:
        return f"i * {step_rad}", comment
    start_rad = mc_float(math.radians(element.start_angle))
    return f"{start_rad} + i * {step_rad}", comment


def _emit_pattern_text_angle_expr(element: PatternElement, part: ResolvedTextPart) -> str:
    """The per-copy Garmin-degrees angle a `shape: text` part's own
    `curve:` draws at (plan 11 slice 2): the part's own local, copy-0 angle
    (`part.curve.angle_garmin`) composed with the copy's rotation, `g0 - i *
    step_deg` with `element.start_angle` folded into `g0` -- the same shape
    an `arc` part's `start_angle` gets (`_emit_pattern_part`).  A clockwise
    design-degree rotation is a plain Garmin-degree subtraction whichever
    `curve.style` produced the local angle, so this never needs to know
    which; a linear pattern's start/step are `0.0`, leaving the local angle
    unchanged on every copy.  `local`/`start`/`step` are the same three
    terms `PatternTextAngle` gives the lint ink and the preview
    (`copy_curve_angle`) -- this reads them off the same object, but folds
    `start` into a build-time literal with `local` and multiplies `step` by
    the runtime copy index `i`, instead of calling the host evaluator.
    Full derivation: `docs/lore/codegen.md` ("Vector fonts and `curve:` on
    a pattern's own `shape: text` part").
    """
    step = element.step_angle if element.pattern == "radial" else 0.0
    angle = PatternTextAngle(part.curve.angle_garmin, element.start_angle, step)
    g0 = mc_float(angle.local - angle.start)
    if element.pattern == "radial":
        return f"{g0} - i * {mc_float(angle.step)}"
    return g0


def _emit_pattern_text_call(
    w: Writer, element: PatternElement, part: ResolvedTextPart, part_prefix: str, radial: bool,
    font_expr: str, value_code: str, justify: str, x_expr: str, y_expr: str,
) -> None:
    """One `dc.drawText`/`drawAngledText`/`drawRadialText` call for one copy
    of a `shape: text` pattern part, at the given screen-space anchor: plain
    `dc.drawText` for an upright part, `drawAngledText`/`drawRadialText`
    under its own `curve:`.  The interior pass and every `outline:` stamp
    share it (the pattern-level twin of `shapes.emit_plain_text_call`/
    `wfb.kinds.text._emit_vector_draw_call`); ``x_expr``/``y_expr`` arrive already
    rotated/translated, and a stamp's screen-space offset commutes with
    both the copy's rotation and the curve angle (research 14 §3.2).
    """
    curve_style = part.curve.style
    if curve_style is None and not radial:
        groups = [f"{x_expr}, {y_expr}, {font_expr}", value_code, justify]
    elif curve_style is None:
        groups = [x_expr, f"{y_expr}, {font_expr}, {value_code}", justify]
    elif curve_style == "angled":
        angle_expr = _emit_pattern_text_angle_expr(element, part)
        groups = [x_expr, f"{y_expr}, {font_expr}, {value_code}", f"{justify}, {angle_expr}"]
    else:  # "radial"
        angle_expr = _emit_pattern_text_angle_expr(element, part)
        direction = RADIAL_DIRECTION[part.curve.direction or "clockwise"]
        radius_expr = radial_radius_expr(f"Layout.{part_prefix}_RADIUS", part.vertical_align,
                                         part.curve.direction, font_expr)
        groups = [x_expr, f"{y_expr}, {font_expr}, {value_code}",
                  f"{justify}, {angle_expr}, {radius_expr}", f"Graphics.{direction}"]
    callee = {None: "dc.drawText", "angled": "dc.drawAngledText"}.get(curve_style, "dc.drawRadialText")
    w.call(callee, groups)


def _emit_pattern_text_draw(
    w: Writer, element: PatternElement, part: ResolvedTextPart, part_prefix: str, radial: bool,
    font_expr: str, value_code: str, justify: str, aod: AodStyle,
) -> None:
    """One copy's `shape: text` part: this copy's own anchor, then --
    ahead of the interior pass, inside the same vector-font null guard --
    the part's own `outline:` stamp loop, if it has one (plan 15 §14
    slice 2), then the interior call itself (`_emit_pattern_text_call`).

    **Gate 4 is never omitted, on any device, in either `if_unavailable:`
    mode** (`docs/research/12-vector-fonts.md` §1, `wfb.kinds.text.
    _emit_vector_text_draw`'s own precedent): a vector font's draw
    call is wrapped `if (<font local> != null)` regardless of `curve_style`
    -- an upright vector-font pattern text part needs the same null guard a
    curved one does, since `Graphics.getVectorFont` can return null even
    when every build-time gate passed. `font_expr` is already a *local*,
    loaded once before the copy loop by `emit_draw` (never a repeated
    field access), so this is a plain local `if`, not the field-narrowing
    trap `docs/lore/monkeyc.md` warns about. A baked custom font never
    reaches this guard: `emit_draw`'s own pre-loop loading early-returns
    on a null baked font instead (a structural resource-load failure, not
    the ordinary case a vector font's null is), so `part.font.is_vector`
    alone decides which of the two this part gets. `outline:`'s stamp loop
    and the interior call both move inside this one guard together, never
    two guards -- the same shape `wfb.kinds.text._emit_vector_text_draw`
    already uses for a standalone element (plan 15 §5/§8).

    **The ring colour, and its own `dc.setColor` restore, are entirely
    local to this one part's own draw sequence** -- they do not interact
    with `emit_draw`'s own colour hoisting (`hoist_color`/
    `current_color`, tracking each part's *interior* `color:` across the
    whole per-copy loop): the sequence below always leaves `dc`'s colour
    state at `part.color`'s own value -- restyled for the AOD frame by
    the same `aod.part_color` the outer loop uses -- by the time it
    returns, exactly the value the outer loop already believed was current
    both before and after, so the outer loop's own bookkeeping needs no
    change. The ring itself takes no `aod:` override key (a pattern's
    `aod: {color: ...}` is the parts' ink, not their rings); it is only
    dimmed, like every other colour the AOD frame draws.
    """
    curve_style = part.curve.style
    if radial:
        # `bottom` shifts the shared `cy` translation term only for this
        # call, not the variable itself (other parts of the same copy
        # still rotate about the unshifted origin) -- the subtraction
        # lands outside the rotation, so it moves the drawn point
        # straight up on screen regardless of `theta`. Skipped entirely
        # under `curve:`: `vertical_align: bottom` is rejected there
        # (`Builder.build_curve`), and `center`/`top` need no
        # y-shift -- `curve:`'s own vertical alignment is a `justify` flag,
        # never a coordinate shift (plan 11 §2.3).
        cy_expr = "cy" if curve_style is not None else glyph_y_expr(
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
        y_expr = oy_expr if curve_style is not None else glyph_y_expr(
            oy_expr, part.vertical_align, font_expr)

    with w.block_if(f"if ({font_expr} != null)" if part.font.is_vector else None):
        if part.outline_color is not None:
            # `index_var`/`offsets_var` are unique per part (`part_prefix`
            # already is): the copy loop wrapping this whole method already
            # declares its own `var i`, and several outlined text parts can
            # share this one generated method (`emit_outline_loop`).
            emit_outline_loop(
                w, f"Layout.OUTLINE_OFFSETS_{part.outline_width}",
                aod.dimmed(element, part.outline_color), x_expr, y_expr,
                lambda ox_, oy_: _emit_pattern_text_call(
                    w, element, part, part_prefix, radial, font_expr, value_code, justify,
                    ox_, oy_),
                index_var=f"outlineI{part_prefix}", offsets_var=f"outlineOffsets{part_prefix}",
            )
            w.line(f"dc.setColor({aod.part_color(element, part.color)}, "
                   "Graphics.COLOR_TRANSPARENT);")
        _emit_pattern_text_call(
            w, element, part, part_prefix, radial, font_expr, value_code, justify,
            x_expr, y_expr)


def _emit_pattern_part(w: Writer, element: PatternElement, prefix: str, index: int,
                       part: ResolvedHandPart, radial: bool, hoist_pen: bool, text_fonts: dict[str, str],
                       thickness_override: str | None, aod: AodStyle) -> None:
    """One template part, drawn for the current copy `i`: polygon/line/
    circle parts go through `rotated.emit_transformed_part` (rotated for a radial
    pattern, translated for a linear one, exactly as a hand's parts are).
    An `arc` part always goes through `WfbArc.drawSpan`, its start angle
    turned by plain degree subtraction.  A `text` part moves only its
    anchor (`WfbGeom.rotatedX`/`rotatedY`, or `ox + ...`), unless its own
    `curve:` turns the glyphs too (`_emit_pattern_text_draw`); its value is
    the IR part's `text:` literal or `value:` compiled through
    `formatting.emit`, since geometry resolution never touches either.
    ``text_fonts`` maps a custom font's resource name to the local
    `emit_draw` loaded it into before the loop.
    """
    part_prefix = f"{prefix}_{index}"
    if part.shape == "text":
        ir_part = element.parts[index]
        assert ir_part.shape == "text"  # resolved parts are the IR parts, 1:1
        if ir_part.text_literal is not None:
            escaped = ir_part.text_literal.replace("\\", "\\\\").replace('"', '\\"')
            value_code = f'"{escaped}"'
        else:
            assert ir_part.text_value is not None  # `text:` or `value:`, never neither
            value_code = formatting.emit(
                ir_part.format or "{}",
                ir_part.text_value.code,
                ir_part.text_value.value.type,
            )
        justify = " | ".join(f"Graphics.{flag}" for flag in part.justify)
        if part.font.is_custom:
            font_expr = text_fonts[part.font.reference]
        else:
            font_expr = f"Graphics.{part.font.reference}"
        _emit_pattern_text_draw(w, element, part, part_prefix, radial, font_expr, value_code,
                                justify, aod)
        return
    thickness_expr = aod.value(thickness_override, f"Layout.{part_prefix}_THICKNESS")
    if part.shape != "arc":
        rotated.emit_transformed_part(w, part, part_prefix, radial=radial,
                                      thickness_expr=thickness_expr, set_pen=not hoist_pen)
        return
    # arc: always centred on the copy's own origin.  A radial pattern
    # turns the author start angle by plain degree subtraction -- the same
    # arithmetic `wfb.layout.garmin_arc` performs at build time for a
    # standalone `shape: arc`, just with `i * step` folded in at runtime --
    # so copy 0 of a radial pattern's arc reaches `WfbArc.drawSpan` with
    # exactly the numbers a `shape: arc` of the same angles would.  A
    # linear pattern never turns at all, so its arc keeps copy 0's angles
    # unchanged at every copy, and only its centre moves.
    g0 = mc_float(90.0 - (part.start_angle + element.start_angle))
    sweep = mc_float(part.sweep)
    if radial:
        step_deg = mc_float(element.step_angle)
        start_arg = f"{g0} - i * {step_deg}"
        cx_arg, cy_arg = "cx", "cy"
    else:
        start_arg = g0
        cx_arg, cy_arg = "ox", "oy"
    w.call("WfbArc.drawSpan", [
        f"dc, {cx_arg}, {cy_arg}, Layout.{part_prefix}_RADIUS, {thickness_expr}",
        f"{start_arg}, {sweep}",
    ])


class PatternKind(ElementKind[PatternElement, PlacedPattern]):
    name = "pattern"
    ir_class = PatternElement
    placed_class = PlacedPattern
    antialiased = True

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
                f"{element_id}: 'modes:' may not include 'low_power' on a pattern",
                b.doc.span(node, "modes") or common["span"],
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
        # compiled to the generated loop's own index (`emit_draw`).
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
            when_absent=node.get("when_absent"),
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
                "a pattern's 'aod: {font: ...}' override is not implemented yet (plan 14)",
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
                if_unavailable=part.if_unavailable, curve=part.curve))
        return runs

    def draw_preview(self, renderer: Renderer, placed: PlacedPattern) -> None:
        """`type: pattern` -- one template, drawn once per copy through
        :meth:`PlacedPattern.transform`: the very same `(ox, oy, sin, cos)`
        the generated draw method computes on the device. Copies draw
        ascending, parts in list order within a copy -- the generated
        nested-loop order. A polygon/line/circle part reuses `hand_part`;
        an `arc` part turns its start angle with the copy instead
        (`_pattern_arc`); a `text` part draws at the copy's own rounded
        anchor (`_pattern_text`).

        `when_absent: hide` is checked once for the whole element
        (`_pattern_absent`), the device's own pre-loop null guard. Per copy,
        each part's own `visible:` is evaluated with `copy` bound, the same
        `values` its colour uses.
        """
        element = placed.element
        if _pattern_absent(renderer, element):
            return
        s = renderer.scale
        for index in placed.copies:
            ox, oy, sin_t, cos_t = placed.transform(index)
            # `copy` is the generated loop's `i`: a colour reading it is
            # evaluated afresh for every copy, exactly as the device does.
            values = {**renderer.values, expr.COPY: index}
            for part_index, part in enumerate(placed.parts):
                if not renderer.visible(element.parts[part_index].visible, values):
                    continue
                if part.shape == "arc":
                    _pattern_arc(renderer, placed, part, ox, oy, index, values)
                elif part.shape == "text":
                    _pattern_text(renderer, placed, part, ox, oy, sin_t, cos_t, index, values)
                else:
                    renderer.hand_part(placed, part, ox * s, oy * s, sin_t, cos_t, values)

    def emit_draw(self, w: Writer, resolved: ResolvedFace, placed: PlacedPattern,
                  value_guards: list[str] | None, plan: ReadPlan,
                  aod: AodStyle = NO_AOD) -> None:
        """`type: pattern` -- loop over the drawn copies, turning (radial) or
        translating (linear) the template resolved once at build time.  The
        same bargain `wfb.kinds.hands.HandsKind.emit_draw` already struck for
        analog hands: the device performs the one piece of layout arithmetic
        ADR 0004 leaves it (a
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
        loop** -- the same "load once, guard once" rule
        `wfb.kinds.text._emit_text_draw` follows for a standalone `text`
        element, just hoisted out of the per-copy body since every copy shares
        one font.  Two text parts naming different fonts
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
        `wfb.kinds.text._emit_vector_text_draw` already does.
        """
        element = placed.element
        prefix = const_prefix(placed.id)
        # `aod: {color: ...}`/`{thickness: ...}` (plan 14 §5.1): one override,
        # applied uniformly to every part, hoisted or not.
        thickness_override = rotated.aod_thickness_override(placed, prefix)
        # `element.parts[i]` and `placed.parts[i]` are the same template, in the
        # same order (`resolve` builds one `ResolvedHandPart`
        # per `HandPart`, 1:1) -- so the IR part is what carries `visible:`
        # (geometry resolution never touches it), read here by plain index.
        live = [
            (index, part) for index, part in enumerate(placed.parts)
            if not ((visible := element.parts[index].visible) is not None
                    and visible.is_constant)
        ]
        radial = element.pattern == "radial"
        needs_trig = _pattern_needs_math(placed)

        if radial:
            w.line(f"var cx = Layout.{prefix}_X;")
            w.line(f"var cy = Layout.{prefix}_Y;")

        text_fonts: dict[str, str] = {}
        vector_text_fonts: set[str] = set()
        for _, part in live:
            if (part.shape == "text" and part.font.is_custom
                    and part.font.reference not in text_fonts):
                text_fonts[part.font.reference] = f"font{len(text_fonts)}"
                if part.font.is_vector:
                    vector_text_fonts.add(part.font.reference)
        for reference, local in text_fonts.items():
            w.line(f"var {local} = _{font_field(reference)};")
            if reference not in vector_text_fonts:
                with w.block(f"if ({local} == null)"):
                    w.line("return;  // the font resource failed to load")
            w.blank()

        # Colour: one distinct part colour is set once, before the loop; several
        # are set inside it, only on each change (the same rule
        # `wfb.kinds.hands._emit_one_hand` already follows within one hand).
        # A colour that reads `copy` is the
        # loop's own `i`, so it can never be hoisted: it is set inside the loop,
        # afresh on every copy.  (A data reading needs no such care -- its local
        # is declared at the top of the method, before the loop.)  A dead part
        # (constant-false `visible:`, excluded from `live`) contributes no
        # colour at all -- it never draws, so its colour is nobody's concern.
        colors = [aod.part_color(element, part.color) for _, part in live]
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
            hoisted_thickness_expr = aod.value(
                thickness_override, f"Layout.{prefix}_{hoist_index}_THICKNESS")
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
            elif element.pattern == "grid":
                # Number / Number is integer division in Monkey C: the row.
                w.line(f"var ox = Layout.{prefix}_X + (i % {element.columns}) * Layout.{prefix}_DX;")
                w.line(f"var oy = Layout.{prefix}_Y + (i / {element.columns}) * Layout.{prefix}_DY;")
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
                with w.block_if(f"if ({visible.code})" if visible is not None else None):
                    _emit_pattern_part(w, element, prefix, index, part, radial, hoist_pen,
                                       text_fonts, thickness_override, aod)
        if hoist_pen:
            w.line("dc.setPenWidth(1);")

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
        for index, part in enumerate(placed.parts):
            outline_color = part.outline_color if part.shape == "text" else None
            yield (f"{placed.id}.parts[{index}]", part.color, outline_color,
                   part.shape != "text")


KIND = PatternKind()
