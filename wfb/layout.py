"""Stage 3: resolve a device-independent design to absolute pixels.

ADR 0004: nothing relative survives into generated Monkey C.  The device does no
layout arithmetic -- it saves both memory and per-frame cost, and it is what lets
the preview renderer consume the *same* resolved geometry the device draws from,
so preview and device cannot disagree about position.

The resolver is a pure function of (design, device, baked fonts), so it is
directly unit-testable with no Garmin toolchain.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import catalog, complications, formatting, icons, units
from .devices import Device, FontMetric
from .diagnostics import Span
from .fonts import BakedFont, fallback
from .catalog import Type
from .ir import (
    ComplicationSlot, Curve, Element, Expression, Face, FontSpec, Graph, Group,
    HandPart, HandsElement, IconElement, PatternElement, Position, Progress, Shape, Size,
    Text, draw_sort_key,
)
from .units import Angle, Axis, Box, IntBox, Length


@dataclass
class Placed:
    """One element, resolved for one device."""

    element: Element
    #: The pixels this element can touch.  Drives clip rectangles, safe-area and
    #: overlap checks, and the AMOLED luminance estimate.
    box: IntBox
    center: tuple[int, int]
    depth: int = 0

    @property
    def id(self) -> str:
        return self.element.id

    @property
    def kind(self) -> str:
        return self.element.kind


#: A hand frame has no parent box -- only `px`/`%r` reach a hand-frame
#: length (schema-enforced), and neither reads `box` at all, so this never
#: leaks a real dimension into a resolved coordinate.  Mirrors
#: `wfb.units._UNUSED_BOX`'s own reasoning for `pixel_size`.
_HAND_FRAME_BOX = Box(0.0, 0.0, 0.0, 0.0)


def round_half_away(value: float) -> int:
    """Round half away from zero: a mirrored ``dx: -1.5px``/
    ``dx: 1.5px`` pair must resolve to ``-2``/``2``, so a symmetric hand
    stays symmetric on the panel.

    Plain ``round()`` (round half *to even*) happens to be sign-symmetric
    too, but lands on a different integer for some ``.5`` cases (``0.5``
    rounds to ``0``, not ``1``).  The one implementation, imported by
    `wfb.preview` for the same distinction over `WfbArc`'s degrees, rather
    than kept as two copies that could drift apart.
    """
    return int(value - 0.5) if value < 0 else int(value + 0.5)


def alignment_shift(width: float, height: float, align: str, vertical_align: str) -> tuple[float, float]:
    """How far a placement box's centre sits from the point ``at:`` resolves
    to, for a box-drawn kind: ``align``/``vertical_align`` say which edge
    (or the centre) of the box sits on that point, independently per axis.
    ``center``/``center`` -- the default -- adds exactly ``0.0`` on both
    axes, so a design that never sets either key resolves unchanged.

    The one implementation of the rule for every box-drawn kind:
    :meth:`Resolver._group_box`, :meth:`Resolver._resolve_text`'s lint box
    and :func:`_pattern_part_ink`'s text branch all call this instead of
    keeping their own ``left``/``center``/``right`` dict literal, as do
    :meth:`Resolver._resolve_shape` (rectangle, rounded_rectangle, ellipse,
    circle, arc -- not polygon or line), :meth:`Resolver._resolve_progress`
    (both styles) and :meth:`Resolver._resolve_graph`.
    :meth:`Resolver._resolve_icon`'s lint box (a glyph kind's own box is
    still moved this way, even though the runtime anchor is not) and
    :meth:`Resolver._resolve_complication_slot`'s estimated box call it as
    well. :meth:`Resolver._resolve_hand_part`'s `rectangle`/`circle`
    branches call it a fourth way -- in the part's own frame, before
    `round_half_away`, so the shift turns or steps with the hand or copy
    like the rest of the part -- rather than write another copy.
    """
    dx = {"left": width / 2, "center": 0.0, "right": -width / 2}[align]
    dy = {"top": height / 2, "center": 0.0, "bottom": -height / 2}[vertical_align]
    return dx, dy


def garmin_arc(start: float, sweep: float) -> tuple[float, str]:
    """The author's arc angles in Garmin's ``drawArc`` convention.

    The format measures degrees clockwise from 12 o'clock; ``drawArc`` measures
    them counter-clockwise from 3 o'clock, so a positive (clockwise) sweep
    travels in the ``ARC_CLOCKWISE`` direction from ``90 - start``.

    There is deliberately **one** of these: `progress` with `style: arc` and
    `shape: arc` both call it, so the two can never drift into two conventions
    that agree on the common cases and disagree on the corners.
    """
    return (
        (90.0 - start) % 360.0,
        "ARC_CLOCKWISE" if sweep >= 0 else "ARC_COUNTER_CLOCKWISE",
    )


def garmin_curve_angle(style: str, angle: Angle) -> float:
    """`curve.angle` (`text.curve`/`patternCurve`, both `style:`s), in
    Garmin's `Dc.drawAngledText`/`Dc.drawRadialText` convention (degrees
    counter-clockwise from 3 o'clock) -- the one place this conversion
    happens, the same "exactly one convention" precedent `garmin_arc` sets
    for `shape: arc`/`progress: {style: arc}` just above.

    The two `curve:` styles share the `angle:` key and its units, but
    answer genuinely different questions, so they convert differently.
    **`radial`'s angle is a POSITION** -- where around the circle the text
    starts -- the same "which way from the centre" quantity every other
    angle in this format answers (arc start angles, hand angles, a
    pattern's own `start_angle:`), confirmed against `drawRadialText`'s own
    doc ("Angle to a point on the circle to justify text"): it keeps this
    format's universal 12-o'clock-zero/clockwise convention and converts
    through `Angle.to_garmin()` exactly like those. **`angled`'s angle is a
    ROTATION** -- how far the text's own baseline is tilted away from
    level, not a direction from any centre -- so `0deg` means "unrotated",
    not "pointing at 12 o'clock": converting it needs none of `to_garmin`'s
    90-degree offset (which exists only to re-anchor a *position*'s zero
    from 12 o'clock to 3 o'clock), just the sign flip that turns this
    format's clockwise-positive sense into Garmin's counter-clockwise-
    positive one. Confirmed against `drawAngledText`'s own doc ("Angle of
    the text baseline in degrees counter-clockwise from the 3 o'clock
    position"): Garmin's own `0` is already a horizontal, level baseline,
    matching this format's `0deg` = level exactly, with no offset needed.

    A radial *pattern*'s own per-copy composition
    (`wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr`,
    `_pattern_part_ink` below) still works unmodified for either style:
    composing a *local* Garmin angle with a copy's own rotation (`design
    clockwise degrees`, converted by straight negation) is valid whether
    that local angle came from a position (`to_garmin`, offset folded in
    once) or a rotation (no offset to begin with) -- the offset, when
    there is one, is a fixed constant contributed once by the part's own
    local angle, never by the per-copy delta being composed with it.
    """
    if style == "radial":
        return angle.to_garmin()
    return (-angle.degrees) % 360.0


def radial_text_angle_span(
    curve_angle_garmin: float, direction: str | None, align: str,
    total_advance: float, radius: float,
) -> tuple[float, float]:
    """The Garmin-degree interval a `curve: {style: radial}` run actually
    sweeps -- derived the same way `wfb.preview._draw_radial_vector_text`
    places each glyph, rather than a second, independently-invented model
    that could silently disagree with it (that function's own docstring
    carries the facing/direction derivations this reuses unchanged).

    The run covers a pixel range of `total_advance` (the whole string's
    measured width) starting `align_offset` pixels *before* the anchor
    (`align: left` starts exactly at `curve_angle_garmin`; `right` ends
    there; `center` straddles it) -- exactly `_draw_radial_vector_text`'s
    own `pixel_offset = pen - align_offset`, evaluated at the run's two
    ends (`pen = 0` and `pen = total_advance`) instead of per glyph.
    Dividing by `radius` turns that pixel range into an angular one, and
    `direction` supplies the sign Garmin angle changes as the pen advances
    (`direction_sign` there: `+1` for `counter_clockwise`, `-1` for
    `clockwise`).  Returned as `(theta_a, theta_b)`, **not** ordered
    min-before-max -- `arc_bbox` below takes them either order.
    """
    counter_clockwise = direction == "counter_clockwise"
    direction_sign = 1.0 if counter_clockwise else -1.0
    align_offset = {"left": 0.0, "center": total_advance / 2.0, "right": total_advance}[align]
    theta_a = curve_angle_garmin - direction_sign * math.degrees(align_offset / radius)
    theta_b = curve_angle_garmin + direction_sign * math.degrees((total_advance - align_offset) / radius)
    return theta_a, theta_b


def arc_bbox(
    cx: float, cy: float, r_inner: float, r_outer: float,
    theta_a_degrees: float, theta_b_degrees: float,
) -> Box:
    """The axis-aligned bounding box of an annulus sector: the ring between
    radii `r_inner`..`r_outer` (`r_inner` clamped to `>= 0`, so a sector
    that would dip past the centre just becomes a pie slice instead of
    wrapping to the far side), swept through the Garmin-angle interval
    between `theta_a_degrees` and `theta_b_degrees` (either order) --
    degrees counter-clockwise from the 3 o'clock position, screen y down
    (`px = cx + r*cos(theta), py = cy - r*sin(theta)`), the same
    convention `wfb.layout.Resolver._rotated_text_box` and
    `wfb.preview._draw_radial_vector_text` both already use.

    The classic arc-bbox bug: the four corner points (both radii at both
    angular ends) are not enough on their own. An arc that crosses due
    north, say, has its topmost point *mid-sweep* -- at neither endpoint --
    so the four axis-aligned extremes (Garmin 0/90/180/270 degrees: 3, 12,
    9 and 6 o'clock) are added too, each at the OUTER radius, whenever that
    direction actually falls inside the swept interval. The inner radius is
    never the extreme there: it is closer to the centre than a corner
    already collected, in every direction.
    """
    theta_min, theta_max = min(theta_a_degrees, theta_b_degrees), max(theta_a_degrees, theta_b_degrees)
    sweep = theta_max - theta_min
    r_inner = max(0.0, r_inner)
    xs: list[float] = []
    ys: list[float] = []
    for theta in (theta_min, theta_max):
        rad = math.radians(theta)
        cos_t, sin_t = math.cos(rad), math.sin(rad)
        for r in (r_inner, r_outer):
            xs.append(cx + r * cos_t)
            ys.append(cy - r * sin_t)
    if sweep >= 360.0:
        # A full turn: every axis extreme is included -- equivalent to the
        # ordinary full-circle-at-r_outer box (a superset of adding the
        # four points one at a time below, and cheaper to state directly).
        xs += [cx - r_outer, cx + r_outer]
        ys += [cy - r_outer, cy + r_outer]
    else:
        for axis_theta in (0.0, 90.0, 180.0, 270.0):
            if (axis_theta - theta_min) % 360.0 <= sweep:
                rad = math.radians(axis_theta)
                xs.append(cx + r_outer * math.cos(rad))
                ys.append(cy - r_outer * math.sin(rad))
    return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _arc_box(
    radius: int, pen: int, cx: float, cy: float, align: str, vertical_align: str,
    start_angle: Angle | None, sweep_angle: Angle | None,
) -> tuple[IntBox, float, float, float, float, float, str]:
    """The geometry `shape: arc` and `progress: {style: arc}` share once
    `radius`/`pen` (a shape's own `max(1, thickness)`, a progress's own
    `max(1, round(...))`) are already resolved: the alignment shift by the
    full circle -- `start_angle:`/`sweep:` never move the centre -- the
    pen's own reach (the same reach a `progress` arc
    claims: the pen straddles the radius, so the ink runs half a pen width
    past it either side), and the author-to-Garmin angle conversion
    (`garmin_arc`).

    Takes `radius`/`pen` already resolved rather than resolving them itself:
    the two callers' own `_extent` calls for `radius` and `thickness` run in
    opposite order (`_resolve_shape` resolves `thickness` before dispatching
    to the `arc` branch, `_resolve_progress` resolves `radius` first inside
    it), and preserving each one's own order is what keeps `Resolver.
    sub_pixel`'s record order unchanged, so that part stays in each caller.

    Returns ``(box, cx, cy, start_degrees, sweep_degrees, garmin_start,
    garmin_direction)`` -- the shifted centre, since both callers embed it
    in their own `Placed*.center`.
    """
    dx, dy = alignment_shift(2 * radius, 2 * radius, align, vertical_align)
    cx, cy = cx + dx, cy + dy
    reach = radius + pen // 2 + 1
    box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
    start = (start_angle or Angle(0.0)).degrees
    sweep = (sweep_angle or Angle(360.0)).degrees
    garmin_start, direction = garmin_arc(start, sweep)
    return box.rounded(), cx, cy, start, sweep, garmin_start, direction


@dataclass
class PlacedShape(Placed):
    radius: int = 0
    corner_radius: int = 0
    thickness: int = 1
    end: tuple[int, int] = (0, 0)
    #: `shape: ellipse` only: the semi-axes, ``width/2`` and ``height/2``.
    rx: int = 0
    ry: int = 0
    #: The rectangle handed to ``fillRectangle``/``drawRectangle``, when that is
    #: not ``box``.  An *outlined* rectangle strokes its edge, so the ink
    #: straddles the declared rectangle and ``box`` -- the pixels the element
    #: can touch, which is what the safe-area and overlap checks read -- is half
    #: a pen width larger all round.  ``None`` means the two coincide.
    rect: IntBox | None = None
    #: `shape: polygon` only: the resolved vertices, in author order.
    points: tuple[tuple[int, int], ...] = ()
    #: `shape: arc` only.  Author degrees (12 o'clock = 0, clockwise), kept for
    #: the preview renderer, then the same pair `PlacedProgress` carries in
    #: Garmin's own convention, ready for `WfbArc.drawSpan`.
    start_angle: float = 0.0
    sweep: float = 360.0
    garmin_start: float = 90.0
    garmin_direction: str = "ARC_CLOCKWISE"


@dataclass
class PlacedText(Placed):
    #: The point passed to ``drawText``; ``justify`` says how text sits on it.
    #: For `curve: {style: radial}`, this is the **centre of the circle**
    #: (plan 11 §2.2's `at:` reinterpretation), not a `drawText`-style
    #: anchor -- codegen's radial branch reads it that way.
    anchor_point: tuple[int, int] = (0, 0)
    justify: tuple[str, ...] = ()
    font_reference: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    font_px: int = 0
    #: The device's `FontMetric` for a system font, **or for a resolved
    #: vector font** (plan 11 §4: `Resolver._vector_font_metric` -- a
    #: synthetic metric naming the resolved face's real filename, so
    #: `wfb.fonts.fallback.measure`/`line_height`/`system_face` locate and
    #: measure the exact same TTF a later preview step would draw with, the
    #: same "one measurement path" discipline plan 09 R2.3 already applies
    #: to a system font). `None` only for a **baked** custom font (`font_is_
    #: custom and not font_is_vector`), or when the device has no pixel
    #: metrics for a plain system-font symbol at all.
    font_metric: FontMetric | None = None
    widest: str = ""
    measured_width: int = 0
    #: True when the extent was estimated rather than measured from real metrics.
    width_is_estimated: bool = False
    #: **Vector fonts only** (plan 11 §2.1/§3). The single face name this
    #: device actually publishes, resolved from `FontSpec.face`'s
    #: author-ordered candidates by :meth:`Resolver._resolve_vector_face` --
    #: what codegen emits as `:face`, never the array (see that method's
    #: docstring for why). Empty when `font_is_vector` is false, or when
    #: gates 1-3 (`docs/research/12-vector-fonts.md` §3) all failed on this
    #: device (:attr:`font_available` is then also false).
    font_face: str = ""
    #: True when `element.font` names a `face:` (vector) `FontSpec` --
    #: `False` for a baked custom font and for a system font alike, so a
    #: caller can tell "device-resident, resolved per device" apart from
    #: "the same font resource on every target" with one flag instead of
    #: re-deriving it from `font_is_custom` plus a `Face.fonts` lookup.
    font_is_vector: bool = False
    #: **Vector fonts only.** Whether gates 1-3 all passed for this element
    #: on *this* device -- always `True` for a baked or system font, which
    #: cannot fail to be available (nothing to gate). `False` here is what
    #: `if_unavailable: hide` acts on (`wfb.lint.check_vector_font_
    #: availability`): the element still resolves -- draw order, a box for
    #: the geometry lints, everything else -- but `font_face` is empty and
    #: nothing about it is ever emitted as a real device-resident face on
    #: this device. `if_unavailable: error` never lets an unavailable
    #: element reach a real build (`wfb.build.resolve_all` fails the whole
    #: build first), so a `False` here only ever survives into a
    #: `ResolvedFace` under `hide`, or in a layout-only test that calls
    #: `wfb.layout.resolve` directly without that build-level check.
    font_available: bool = True
    #: `text.curve.style` as authored (plan 11 §2.2) -- `"angled"` |
    #: `"radial"` | `None` for ordinary upright text. Kept on the placed
    #: element (not just reachable through `element.curve`) so a lint or
    #: the emitter never has to re-derive "is this element curved" from the
    #: IR once layout has already answered it.
    curve_style: str | None = None
    #: `text.curve.angle`, **in the design's own author-facing units** --
    #: kept alongside :attr:`curve_angle_garmin` exactly as `PlacedShape.
    #: start_angle`/`.garmin_start` keep both for `shape: arc`: the
    #: generated `Layout` comment carries both values (plan 11 §2.2), and
    #: the preview reasons in the design's own convention throughout, the
    #: same way it already does for `arc`/`progress`. **Not one convention**:
    #: for `radial` this is a *position* (12 o'clock = 0, clockwise
    #: positive, the same universal direction convention every other angle
    #: in this format uses); for `angled` it is a *rotation* (0 = level/
    #: unrotated, clockwise positive) -- see `garmin_curve_angle`'s own
    #: docstring for why the two differ. `0.0` when `curve_style` is `None`.
    curve_angle_degrees: float = 0.0
    #: `garmin_curve_angle(curve_style, text.curve.angle)` -- Garmin's own
    #: 3-o'clock/counter-clockwise convention, what `Dc.drawAngledText`/
    #: `Dc.drawRadialText`'s own `angle` parameter actually expects, and
    #: what this module's own box math (`Resolver._rotated_text_box`) rotates
    #: by, since that is the rotation the device really draws. `0.0` when
    #: `curve_style` is `None`.
    curve_angle_garmin: float = 0.0
    #: `curve: {style: radial}` only -- the circle's radius, resolved to
    #: whole device pixels the same way any other polar `at:` radius is
    #: (`Resolver._len`, `Axis.MINOR`). `0` for `angled`, which has no
    #: circle.
    curve_radius_px: int = 0
    #: `curve: {style: radial}` only -- `"clockwise"` | `"counter_clockwise"`
    #: | `None`, `text.curve.direction` carried straight through for
    #: codegen to map onto `Graphics.RadialTextDirection`
    #: (`RADIAL_TEXT_DIRECTION_CLOCKWISE`/`_COUNTER_CLOCKWISE`, a later
    #: slice) -- this module never needs the Garmin constant name itself,
    #: only the author's own word.
    curve_direction: str | None = None


@dataclass
class PlacedProgress(Placed):
    radius: int = 0
    thickness: int = 1
    #: Author degrees (12 o'clock = 0, clockwise).  Kept for the preview renderer.
    start_angle: float = 0.0
    sweep: float = 360.0
    #: Garmin degrees (3 o'clock = 0, counter-clockwise), ready for drawArc.
    garmin_start: float = 90.0
    garmin_direction: str = "ARC_CLOCKWISE"
    size: tuple[int, int] = (0, 0)


@dataclass
class PlacedIcon(Placed):
    #: The requested *visual* pixel size -- not the font's own nominal size it
    #: was baked at, which `wfb.icons.bake_size` may inflate to compensate for
    #: how much the icon font's icon sets pad a glyph inside its em-square.
    size: int = 0
    #: The synthetic font resource this icon draws from (see `wfb.icons.font_key`).
    font_key: str = ""
    #: For a static icon, the glyph itself, resolved from `element.icon` (a
    #: catalogue name or a literal character) at IR-build time. For a dynamic
    #: icon (`element.is_dynamic`), the *representative* glyph measurement and
    #: preview use -- `wfb.icons.WEATHER_BAKE_REFERENCE_GLYPH` -- never what
    #: codegen actually draws, which it resolves on-device instead.
    codepoint: str = "?"
    anchor_point: tuple[int, int] = (0, 0)
    #: `Toybox.Graphics.TEXT_JUSTIFY_*` flags, `Resolver._justify`'s own
    #: precedent -- an icon is a glyph kind, so its alignment is a
    #: device-side justify on the unshifted anchor, the same mechanism
    #: `PlacedText.justify` already uses, not a build-time box move.
    justify: tuple[str, ...] = ()


@dataclass
class PlacedGraph(Placed):
    """A `graph`, resolved: the drawn box, and the two style-specific widths.

    Nothing here is series-dependent (`wfb/ir.py`'s `Graph.sample_count` and
    `series_def` already carry everything about *which* series and *how
    many* samples, device-independently) -- this is only the box and the
    two pixel widths a device's screen actually determines.
    """

    thickness: int = 1
    bar_width: int = 1
    size: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class ResolvedHandPart:
    """One hand part, or one pattern template part, resolved for
    one device: whole pixels, in the shared frame (origin = the axis /
    the pattern's own ``at:``, pointing at 12 o'clock) -- the shape the
    watch rotates (or translates) at runtime.  One class
    covers every runtime shape (``polygon``, ``line``, ``circle``, ``arc``)
    the same way :class:`PlacedShape` covers every ``shape:``; a rectangle
    part is folded into ``polygon`` here (`Resolver._resolve_hand_part`),
    because a rotated rectangle is a polygon.  A hand never produces
    an ``"arc"`` part -- `wfb.ir.HAND_PART_REJECTED_SHAPES` refuses it before
    this is reached -- so ``start_angle``/``sweep`` are pattern-only.
    """

    shape: str
    color: Expression | None = None
    #: ``polygon`` (rectangle folded in): vertices in author order.
    points: tuple[tuple[int, int], ...] = ()
    #: ``line``: both ends.
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
    #: ``circle``/``arc``: centre (``arc``'s is always the origin, x=y=0) and
    #: radius; ``line``/unfilled ``circle``/``arc``: pen width.
    x: int = 0
    y: int = 0
    radius: int = 0
    thickness: int = 1
    filled: bool = True
    #: ``arc`` only.  Author degrees (12 o'clock = 0, clockwise) -- a radial
    #: pattern's runtime rotation adds ``start + i * step`` to ``start_angle``;
    #: a linear one leaves it as authored.  The `0.0` default
    #: is never actually relied on: `Resolver._resolve_hand_part` always sets
    #: both explicitly for a real ``arc`` part (`sweep` defaulting to `360deg`
    #: there, not here, when the author omitted it).
    start_angle: float = 0.0
    sweep: float = 0.0
    #: ``text`` only -- ``x``/``y`` double as the part's own
    #: anchor in the template frame (rounded via `round_half_away`, the same as
    #: a circle's centre), everything else stays at its default on every
    #: other shape.  Upright glyphs are *not* rotation-invariant, so unlike
    #: every other shape a text part's own ``reach`` (`Resolver.
    #: _resolve_hand_part`'s return) is always `0.0`: the real farthest-ink
    #: distance is folded into `Resolver._resolve_pattern`'s per-copy loop
    #: instead, where each drawn copy's own upright box is known.
    font_reference: str = ""
    font_is_custom: bool = False
    font_px: int = 0
    #: See `PlacedText.font_metric` -- the same field, for a `shape: text`
    #: pattern part.
    font_metric: FontMetric | None = None
    #: `Toybox.Graphics.TEXT_JUSTIFY_*` flags, `Resolver._justify`'s own
    #: precedent (a `Text` element's `PlacedText.justify`).
    justify: tuple[str, ...] = ()
    align: str = "center"
    vertical_align: str = "center"
    line_height: int = 0
    #: The host-rendered string for every copy index ``0..count-1`` (skipped
    #: copies included, so ``texts[i]`` is copy ``i``), `HandPart.texts`
    #: carried through layout unchanged (device-independent).
    texts: tuple[str, ...] = ()
    #: Each string's measured pixel width, same length and order as
    #: ``texts`` -- a baked font's `measure` or `fonts.fallback.measure` for
    #: a system font, exactly as `Resolver._resolve_text` measures one.
    widths: tuple[int, ...] = ()
    #: See `PlacedText.font_face`/`.font_is_vector`/`.font_available` --
    #: the same three fields, for a `shape: text` pattern part (plan 11
    #: slice 2).  `font_face` is this device's own resolved `:face` string
    #: (empty when unresolved); `font_is_vector` is true only when `font:`
    #: names a `face:` `FontSpec`; `font_available` is gates 1-3's answer
    #: for *this* device, always `True` for a baked/system font.
    font_face: str = ""
    font_is_vector: bool = False
    font_available: bool = True
    #: See `PlacedText.curve_style`/`.curve_angle_degrees`/`.curve_angle_
    #: garmin`/`.curve_radius_px`/`.curve_direction` -- the same five
    #: fields, for a `shape: text` pattern part's own `curve:` (plan 11
    #: slice 2).  **`curve_angle_garmin` is this part's own *local*,
    #: template-frame angle (`HandPart.curve.angle`, Garmin-converted) --
    #: for copy 0 alone, NOT yet composed with a radial pattern's own
    #: per-copy rotation.** That composition (`part.curve_angle_garmin -
    #: (element.start_angle + i * element.step_angle)`, the same "local
    #: angle plus the copy's own rotation" arithmetic a pattern's own `arc`
    #: part's `start_angle` already gets at codegen time) happens in
    #: `wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr` and, for the
    #: lint box, in `_pattern_part_ink` -- never here, since it genuinely
    #: depends on which copy `i` is, a per-copy runtime loop variable this
    #: module never sees. `None`/`0`/`0.0` defaults exactly mirror
    #: `PlacedText`'s own, for an upright (uncurved) text part or any other
    #: shape.
    curve_style: str | None = None
    curve_angle_degrees: float = 0.0
    curve_angle_garmin: float = 0.0
    curve_radius_px: int = 0
    curve_direction: str | None = None


@dataclass(frozen=True)
class ResolvedHand:
    parts: tuple[ResolvedHandPart, ...] = ()


@dataclass
class PlacedHands(Placed):
    """A `type: hands` element, resolved: the axis, each declared hand's
    resolved parts, and the swept disc's reach.

    ``box`` is the square around that disc, and ``center`` is the axis --
    both set by :meth:`Resolver._resolve_hands`, the same shape every other
    ``Placed`` subclass follows.
    """

    hour: ResolvedHand | None = None
    minute: ResolvedHand | None = None
    second: ResolvedHand | None = None
    #: The farthest ink of any part of any drawn hand from the axis --
    #: `circular_extent` reads this instead of `box`, so the visible-area
    #: check reasons about the real disc, not its bounding square.
    reach: float = 0.0


@dataclass
class PlacedPattern(Placed):
    """A `type: pattern` element, resolved: the resolved template, which
    copies are actually drawn, and the repeat rule -- radial (turn about
    `center`) or linear (step by `dx`/`dy`).

    ``box`` is the bounding box of the ink of every *drawn* copy (computed by
    :meth:`Resolver._resolve_pattern` from :meth:`transform`), and ``center``
    is the origin every copy is measured from -- radial's centre of rotation,
    or linear's own copy-0 origin -- the same shape every other ``Placed``
    subclass follows.
    """

    #: The template, copy 0 as authored (rectangle folded into polygon).
    parts: tuple[ResolvedHandPart, ...] = ()
    #: Drawn copy indices, ascending -- `PatternElement.drawn_indices()`.
    copies: tuple[int, ...] = ()
    #: Radial only, degrees: copy 0's angle, and the angle between copies.
    start: float = 0.0
    step: float = 0.0
    #: Linear only, whole pixels: the offset between consecutive copies.
    dx: int = 0
    dy: int = 0
    #: Radial only: the farthest ink of any part from `center`, rotation
    #: -invariant so it needs no per-copy loop (`circular_extent` reads this
    #: instead of `box`, the same reasoning `PlacedHands.reach` follows). 0
    #: for a linear pattern, which reports no disc.
    reach: float = 0.0

    def transform(self, index: int) -> tuple[float, float, float, float]:
        """``(ox, oy, sin, cos)`` for copy ``index``: radial =
        ``(cx, cy, sin(theta), cos(theta))``; linear =
        ``(cx + i*dx, cy + i*dy, 0.0, 1.0)``.  The one formula the preview and
        the extent computation share -- apply it to a
        template point ``(x, y)`` as ``ox + x*cos - y*sin, oy + x*sin +
        y*cos`` (a rotation, which collapses to a plain translation when
        ``sin``/``cos`` are ``0``/``1``).
        """
        if self.element.pattern == "radial":
            theta = math.radians(self.start + index * self.step)
            return float(self.center[0]), float(self.center[1]), math.sin(theta), math.cos(theta)
        return float(self.center[0] + index * self.dx), float(self.center[1] + index * self.dy), 0.0, 1.0


def pattern_text_anchor(
    part: ResolvedHandPart, ox: float, oy: float, sin_t: float, cos_t: float,
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


def _pattern_part_ink(
    part: ResolvedHandPart, ox: float, oy: float, sin_t: float, cos_t: float, index: int,
    copy_angle_degrees: float = 0.0,
) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of one resolved pattern part's ink
    for one copy, given that copy's :meth:`PlacedPattern.transform`:
    polygon vertices; a line's ends padded by half its pen width; a
    circle's centre padded by its radius (plus half the pen width when
    outlined); an arc's full circle -- always centred on the copy's own
    origin -- padded by half its pen width, conservatively ignoring
    `start_angle`/`sweep`; a text part's box, from its rounded anchor
    (:func:`pattern_text_anchor`) and this copy's own measured width
    (``part.widths[index]``) -- the one shape here that needs
    to know *which* copy it is, since upright text is not rotation-invariant.

    `copy_angle_degrees` is this copy's own rotation, in the design's
    clockwise-from-12 convention (`element.start_angle + index *
    element.step_angle` for a radial pattern, `0.0` for a linear one --
    computed once per copy by `Resolver._resolve_pattern`'s own loop, the
    same value `wfb.emit.monkeyc.rotated._emit_pattern_text_angle_expr`
    composes with at codegen time). Unused except by a curved text part's
    own conservative box (plan 11 slice 2): `angled` is the measured
    `width`x`height` rectangle rotated about the anchor by the *effective*
    Garmin angle (`part.curve_angle_garmin - copy_angle_degrees`, the same
    composition codegen performs), reusing `Resolver._rotated_text_box`
    rather than a second copy of that rotation math; `radial` composes the
    same *effective* angle and hands it to `radial_text_angle_span`/
    `arc_bbox` -- the tight annulus-sector box a standalone `curve:
    {style: radial}` text element's own lint box now uses
    (`Resolver._resolve_text`, 2026-09-21 follow-up to plan 11 §4; the
    "centre +/- (radius + line_height)" square it replaced there over-
    reported on a round screen) -- the centre here is this copy's own
    rotated/translated anchor, not a fixed point.
    """
    def tf(x: float, y: float) -> tuple[float, float]:
        return ox + x * cos_t - y * sin_t, oy + x * sin_t + y * cos_t

    if part.shape == "polygon":
        pts = [tf(x, y) for x, y in part.points]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    if part.shape == "line":
        x1, y1 = tf(part.x1, part.y1)
        x2, y2 = tf(part.x2, part.y2)
        pad = part.thickness / 2.0
        return min(x1, x2) - pad, min(y1, y2) - pad, max(x1, x2) + pad, max(y1, y2) + pad
    if part.shape == "circle":
        px, py = tf(part.x, part.y)
        pad = part.radius + (0.0 if part.filled else part.thickness / 2.0)
        return px - pad, py - pad, px + pad, py + pad
    if part.shape == "text":
        ax, ay = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
        width = part.widths[index] if part.widths else 0
        height = part.line_height
        if part.curve_style == "angled":
            effective_garmin = (part.curve_angle_garmin - copy_angle_degrees) % 360.0
            box = Resolver._rotated_text_box(
                ax, ay, width, height, part.align, part.vertical_align, effective_garmin)
            return box.x, box.y, box.x + box.width, box.y + box.height
        if part.curve_style == "radial":
            if part.curve_radius_px > 0:
                effective_garmin = (part.curve_angle_garmin - copy_angle_degrees) % 360.0
                theta_a, theta_b = radial_text_angle_span(
                    effective_garmin, part.curve_direction, part.align, width, part.curve_radius_px)
                box = arc_bbox(ax, ay, part.curve_radius_px - height, part.curve_radius_px + height,
                               theta_a, theta_b)
                return box.x, box.y, box.x + box.width, box.y + box.height
            reach = part.curve_radius_px + height
            return ax - reach, ay - reach, ax + reach, ay + reach
        dx, dy = alignment_shift(width, height, part.align, part.vertical_align)
        left = ax + dx - width / 2.0
        top = ay + dy - height / 2.0
        return left, top, left + width, top + height
    # arc: always centred on the copy's own origin.
    px, py = tf(0.0, 0.0)
    pad = part.radius + part.thickness / 2.0
    return px - pad, py - pad, px + pad, py + pad


#: The placed kinds whose own drawing `antialias:` reaches as a runtime
#: `Dc.setAntiAlias` -- primitives, not glyphs (`text`/`icon` anti-alias in
#: their baked font instead).  One tuple, read by the emitter's "is the
#: feature used" gate, its per-element toggle, and the `antialias-dither`
#: lint: three private copies once drifted, so a hands-only anti-aliased face
#: emitted no `setAntiAlias` at all, and a graph-only one never linted.
ANTIALIASED_PRIMITIVES = (PlacedShape, PlacedProgress, PlacedGraph, PlacedHands, PlacedPattern)


#: Fixed pixel gap between a complication_slot's icon and its reading.  A
#: small constant rather than a fraction of the icon's own size, the same way
#: `PlacedShape`'s outline padding is a fixed `+1`/`+2` rather than scaled --
#: there is no `size:`-like key in the format to derive one from, and getting
#: this exact does not change what the element *is*.  Stays the fallback for
#: a design that never authors `icon_gap:`: the literal
#: `4` a generated view embeds, kept inline rather than
#: promoted to a per-device constant when nothing asked for one.
COMPLICATION_SLOT_ICON_GAP = 4


@dataclass(frozen=True)
class SlotPairGeometry:
    """The icon+reading pair's combined extent, and each piece's offset from
    the pair's own top-left corner -- shared by
    `Resolver._resolve_complication_slot` (the estimated box the geometry
    lints size against), `wfb.preview._complication_slot` (the pixels
    actually drawn, from real measured extents) and mirrored, not called, in
    hand-written Monkey C by `wfb.emit.monkeyc._emit_complication_slot`: the
    real text is not known until the value is pulled at runtime (ADR 0004's
    one deliberate exception), so the device computes the equivalent
    arithmetic itself from `Dc.getTextWidthInPixels`/`Dc.getFontHeight`
    rather than being handed these numbers.
    """

    width: int
    height: int
    icon_x: int
    icon_y: int
    text_x: int
    text_y: int


def complication_slot_pair_geometry(
    position: str, icon_w: int, icon_h: int, text_w: int, text_h: int, gap: int,
) -> SlotPairGeometry:
    """The icon+reading pair's combined box, and each piece's offset within
    it, for one `icon_position:` (`left` (default) | `right` | `top` |
    `bottom`) -- the one place this geometry is computed in Python.

    `icon_w`/`icon_h` are `(0, 0)` when the slot draws no icon at all (no
    declared choice resolves one, or the wearer's live pick does not on the
    device side) -- the gap then drops too and the text centres alone in
    every position, matching plain `left`-only behaviour with no icon.
    """
    has_icon = icon_w > 0 or icon_h > 0
    gap = gap if has_icon else 0
    if position in ("top", "bottom"):
        width = max(icon_w, text_w)
        height = icon_h + gap + text_h
        icon_x = (width - icon_w) // 2 if has_icon else 0
        text_x = (width - text_w) // 2
        if position == "top":
            icon_y = 0
            text_y = icon_h + gap
        else:
            text_y = 0
            icon_y = text_h + gap
        return SlotPairGeometry(width, height, icon_x, icon_y, text_x, text_y)

    width = text_w + (icon_w + gap if has_icon else 0)
    height = max(icon_h, text_h)
    icon_y = (height - icon_h) // 2
    text_y = (height - text_h) // 2
    if position == "right":
        text_x = 0
        icon_x = text_w + gap
    else:  # "left" (default)
        icon_x = 0
        text_x = icon_w + gap if has_icon else 0
    return SlotPairGeometry(width, height, icon_x, icon_y, text_x, text_y)


@dataclass
class PlacedComplicationSlot(Placed):
    """A `complication_slot`, resolved: an estimated box for the geometry
    lints, plus everything the emitter needs to draw the icon and reading it
    cannot know the exact content of until the device pulls it.

    `box`/`widest` are, like `PlacedText`'s, an *estimate* -- the real drawn
    extent depends on which type the wearer has this slot pointed at and
    what it currently reads, neither of which exists at build time.  The
    generated code centres the actually-drawn icon+text pair on `anchor_point`
    at runtime (`Dc.getTextWidthInPixels`), so this box is for the safe-area/
    off-screen checks only, not the device's own placement math.
    """

    anchor_point: tuple[int, int] = (0, 0)
    font_reference: str = "FONT_SMALL"
    font_is_custom: bool = False
    font_px: int = 0
    #: See `PlacedText.font_metric` -- the same field, for the slot's own
    #: reading text.
    font_metric: FontMetric | None = None
    #: The widest plausible reading, across every declared choice -- see
    #: `Resolver._complication_slot_widest`.
    widest: str = ""
    #: The synthetic multi-glyph icon font this slot's icon draws from
    #: (`wfb.icons.font_key`), or `None` when this slot draws no icon at all
    #: -- `icon_size:` was omitted, or none of its declared choices has an
    #: entry in `ConfigDataSlot.icons`.
    icon_font_key: str | None = None
    icon_px: int = 0
    #: `element.icon_position`, carried onto the placed element so the
    #: emitter and preview do not have to reach back into the IR for it.
    icon_position: str = "left"
    #: The resolved pixel gap: `COMPLICATION_SLOT_ICON_GAP` when
    #: `element.icon_gap` is `None` (unauthored), or `element.icon_gap`
    #: resolved for this device otherwise.
    icon_gap_px: int = COMPLICATION_SLOT_ICON_GAP


@dataclass(frozen=True)
class SubPixelLength:
    """A nonzero %/%r extent that resolved below 1 px on this device with
    `min_1px` off -- i.e. it rounds away to nothing here while drawing on
    a target with a larger screen.  Collected by `Resolver`, read by
    `wfb.lint.check_sub_pixel_length`.  Do not change this shape without
    checking who else is coding against it.
    """

    owner: str        # element id; "<id>.parts[<i>]" for a pattern part,
                      # "<id>.<hand>.parts[<i>]" for a hand part (a hand set
                      # has three `parts:` lists, a pattern only one)
    key: str          # the authored key: "thickness", "size.width",
                      # "size.height", "bar_width", "radius"
    length: Length    # as authored, for the message ("0.4%r")
    value: float      # the unclamped resolved value, in device px
    span: Span | None # the authored line: the part's span for a part,
                      # else the element's
    element: Element  # the element to hang `lint: {allow: [...]}` on


@dataclass
class ResolvedFace:
    face: Face
    device: Device
    #: Flattened, in draw order (document order, then any explicit ``z``).
    items: list[Placed]
    fonts: dict[str, BakedFont]
    screen: IntBox
    warnings: list[str] = field(default_factory=list)
    #: Every `SubPixelLength` this device's resolve pass recorded, in resolve
    #: order -- empty on every design that never turns
    #: `min_1px:` off where it would have mattered (nothing here clamps by
    #: default, so nothing here is ever sub-pixel by surprise until an
    #: author writes a relative hairline). Not deduplicated: one record per
    #: resolved length, same key repeated across devices where it recurs --
    #: the lint decides how to present them.
    sub_pixel: list[SubPixelLength] = field(default_factory=list)

    def in_mode(self, mode: str) -> list[Placed]:
        return [p for p in self.items if mode in p.element.modes]

    def drawn_in_mode(self, mode: str) -> list[Placed]:
        """``in_mode`` minus groups -- everything that actually paints in ``mode``.

        A group is a pure layout container: it emits no draw method and paints
        nothing of its own (``wfb/emit/monkeyc.py`` skips ``kind == "group"``
        everywhere it walks ``items``). Its box is therefore not evidence of
        anything being drawn there -- and it can be actively misleading, since a
        group with no explicit ``size:`` resolves to its *entire* parent box
        (``Resolver._group_box``). A caller asking "what actually draws in this
        mode" -- a clip rectangle, an element count -- wants this, not
        ``in_mode``.
        """
        return [p for p in self.in_mode(mode) if p.kind != "group"]

    def clip_for(self, mode: str) -> IntBox | None:
        """The tightest rectangle covering everything drawn in ``mode``.

        ``setClip`` is charged by *region area* -- every pixel in the clip counts
        as modified whenever any does -- so this being tight is what keeps
        ``onPartialUpdate`` inside its budget.

        Built from :meth:`drawn_in_mode`, not :meth:`in_mode`: a group paints
        nothing, so its box must not inflate the clip (see ``drawn_in_mode``'s
        docstring -- this was a real bug, fixed after being reproduced: a
        low-power element wrapped in a size-less group blew the clip up to the
        full screen).

        **Unions across every layout, not just the active one.**
        `_configLayout` is a runtime value
        this stage never resolves, so a per-layout clip is not something this
        can compute at all -- and the guard `wfb/emit/monkeyc.py` wraps each
        low-power call in (`_emit_on_partial_update`) only narrows *which*
        calls run, never the clip `setClip` was already given.  A tighter,
        per-layout clip is a real possible optimisation, deliberately not
        built: it would need the clip computed and set *inside* each layout's
        guard, which nothing here or in the emitter does yet.
        """
        boxes = [p.box for p in self.drawn_in_mode(mode)]
        if not boxes:
            return None
        clip = boxes[0]
        for box in boxes[1:]:
            clip = clip.union(box)
        return clip.inflate(1).clamp_to(self.device.width, self.device.height)


class Resolver:
    def __init__(self, face: Face, device: Device, fonts: dict[str, BakedFont]) -> None:
        self.face = face
        self.device = device
        self.fonts = fonts
        self.screen = Box(0, 0, device.width, device.height)
        self.minor_radius = device.minor_radius
        self.items: list[Placed] = []
        self.warnings: list[str] = []
        #: Every `SubPixelLength` recorded so far -- appended
        #: by `_extent`/`_hand_extent`, the only two call sites that can see
        #: "this nonzero relative length is under 1 px and `min_1px` is off
        #: here".
        self.sub_pixel: list[SubPixelLength] = []
        #: The element/part currently being resolved, for `_record_sub_pixel`
        #: to hang a finding on -- set for every element by `_resolve_list`
        #: before it dispatches to that element's own `_resolve_*`, and
        #: narrowed to a `<element id>.parts[<i>]` id/span by
        #: `_resolve_hand_part` while it resolves one hand/pattern part
        #: (`_owner_element` itself stays the owning `hands`/`pattern`
        #: element throughout -- a part has no `lint:` key of its own to
        #: suppress against). `None` only before the first element is
        #: reached, which no call site here ever runs during.
        self._owner_id: str = ""
        self._owner_span: Span | None = None
        self._owner_element: Element | None = None

    def resolve(self) -> ResolvedFace:
        self._resolve_list(self.face.elements, self.screen, depth=0)
        # static content first, then `z`, then document order -- the one key,
        # shared with `Face.draw_order` so the two can never disagree
        self.items.sort(key=lambda p: draw_sort_key(p.element))
        return ResolvedFace(
            face=self.face,
            device=self.device,
            items=self.items,
            fonts=self.fonts,
            sub_pixel=self.sub_pixel,
            screen=IntBox(0, 0, self.device.width, self.device.height),
            warnings=self.warnings,
        )

    # -- traversal --------------------------------------------------------

    def _resolve_list(self, elements: list[Element], parent: Box, depth: int) -> None:
        for element in elements:
            # Set before dispatch, for `_extent`/`_hand_extent` to hang a
            # `SubPixelLength` on (`_record_sub_pixel`) -- every element gets
            # its own id/span/self as the owner; a hand or pattern part
            # narrows id/span further inside `_resolve_hand_part`.
            self._owner_id = element.id
            self._owner_span = element.span
            self._owner_element = element
            if isinstance(element, Group):
                box = self._group_box(element, parent)
                self.items.append(
                    Placed(element, box.rounded(min_1px=element.resolved_min_1px),
                           (round(box.center_x), round(box.center_y)), depth)
                )
                self._resolve_list(element.items, box, depth + 1)
            elif isinstance(element, Shape):
                self.items.append(self._resolve_shape(element, parent, depth))
            elif isinstance(element, Text):
                self.items.append(self._resolve_text(element, parent, depth))
            elif isinstance(element, Progress):
                self.items.append(self._resolve_progress(element, parent, depth))
            elif isinstance(element, IconElement):
                self.items.append(self._resolve_icon(element, parent, depth))
            elif isinstance(element, Graph):
                self.items.append(self._resolve_graph(element, parent, depth))
            elif isinstance(element, ComplicationSlot):
                self.items.append(self._resolve_complication_slot(element, parent, depth))
            elif isinstance(element, HandsElement):
                self.items.append(self._resolve_hands(element, parent, depth))
            elif isinstance(element, PatternElement):
                self.items.append(self._resolve_pattern(element, parent, depth))

    # -- per-kind ---------------------------------------------------------

    def _sized_shift(
        self, size: Size, parent: Box, cx: float, cy: float, align: str, vertical_align: str, *,
        min_1px: bool,
    ) -> tuple[float, float, float, float]:
        """Width, height (`_extent`, width then height -- the order every
        `SubPixelLength` record relies on) and `(cx, cy)` shifted by
        `alignment_shift` -- the "size, then align" placement box
        `_group_box`, `_resolve_shape`'s rectangle/rounded_rectangle/ellipse
        tail, `_resolve_progress`'s bar branch and `_resolve_graph` all
        share.

        Takes the already-resolved anchor point rather than resolving it
        itself: `_resolve_shape` needs that same point earlier, for its
        circle/line/arc/polygon branches, before this is ever reached, and
        `_point` never records a `SubPixelLength` (it calls `_len`, not
        `_extent`), so calling it before or after these two `_extent` calls
        makes no difference to `Resolver.sub_pixel`'s order.
        """
        width = self._extent(size.width, parent, Axis.X, parent.width,
                             min_1px=min_1px, what="size.width")
        height = self._extent(size.height, parent, Axis.Y, parent.height,
                              min_1px=min_1px, what="size.height")
        dx, dy = alignment_shift(width, height, align, vertical_align)
        return width, height, cx + dx, cy + dy

    def _group_box(self, element: Group, parent: Box) -> Box:
        cx, cy = self._point(element.at, parent)
        width, height, cx, cy = self._sized_shift(
            element.size, parent, cx, cy, element.align, element.vertical_align,
            min_1px=element.resolved_min_1px)
        return Box(cx - width / 2, cy - height / 2, width, height)

    def _resolve_shape(self, element: Shape, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        min_1px = element.resolved_min_1px
        thickness = round(self._extent(element.thickness, parent, Axis.MINOR, 1,
                                       min_1px=min_1px, what="thickness"))

        if element.shape == "circle":
            radius = round(self._extent(element.radius, parent, Axis.MINOR, 0,
                                        min_1px=min_1px, what="radius"))
            # The placement box is the full circle (`2*radius` square)
            # regardless of `filled`/`thickness` -- an outline's pen pad is
            # applied to `reach` below, around the already-moved centre, so
            # it never itself moves the shift.
            dx, dy = alignment_shift(2 * radius, 2 * radius, element.align, element.vertical_align)
            cx, cy = cx + dx, cy + dy
            reach = radius if element.filled else radius + max(1, thickness) // 2 + 1
            box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                               radius=radius, thickness=max(1, thickness))

        if element.shape == "line":
            # No `align`/`vertical_align` on a line: `at:` and
            # `to:` are its two ends, so there is no single point to align a
            # box on. `SHAPE_GEOMETRY_KEYS`/`_check_shape_keys` reject the
            # keys before this is ever reached with either one set.
            ex, ey = self._point(element.to or Position(), parent)
            pad = max(1, thickness)
            box = Box(min(cx, ex) - pad, min(cy, ey) - pad,
                      abs(ex - cx) + 2 * pad, abs(ey - cy) + 2 * pad)
            return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                               thickness=max(1, thickness), end=(round(ex), round(ey)))

        if element.shape == "arc":
            radius = round(self._extent(element.radius, parent, Axis.MINOR, 0,
                                        min_1px=min_1px, what="radius"))
            pen = max(1, thickness)
            box, cx, cy, start, sweep, garmin_start, direction = _arc_box(
                radius, pen, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            return PlacedShape(
                element, box, (round(cx), round(cy)), depth,
                radius=radius, thickness=pen,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start, garmin_direction=direction,
            )

        if element.shape == "polygon":
            points = tuple(
                (round(px), round(py))
                for px, py in (self._point(point, parent) for point in element.points)
            )
            if not points:
                # `wfb.ir` has already errored; keep resolving so the rest of
                # the design still gets checked.
                return PlacedShape(element, Box(cx, cy, 0, 0).rounded(),
                                   (round(cx), round(cy)), depth)
            xs = [px for px, _ in points]
            ys = [py for _, py in points]
            box = Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            centre = (round(sum(xs) / len(xs)), round(sum(ys) / len(ys)))
            return PlacedShape(element, box.rounded(), centre, depth, points=points)

        # rectangle, rounded_rectangle, ellipse: the placement box is the
        # declared `size:` -- moved before the outline's pen
        # pad (below) is added, so the pad never itself moves the shift.
        width, height, cx, cy = self._sized_shift(
            element.size, parent, cx, cy, element.align, element.vertical_align, min_1px=min_1px)

        if element.shape == "ellipse":
            rx = round(width / 2)
            ry = round(height / 2)
            # An outline straddles the semi-axis exactly as a circle's does, so
            # it reaches half a pen width further out on both axes.
            pad = 0 if element.filled else max(1, thickness) // 2 + 1
            box = Box(cx - rx - pad, cy - ry - pad, 2 * (rx + pad), 2 * (ry + pad))
            return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                               rx=rx, ry=ry, thickness=max(1, thickness))

        corner = round(self._len(element.corner_radius, parent, Axis.MINOR, 0))
        # `min_1px=min_1px`: this box's width/height is `width`/`height`
        # straight from `_extent` above, the exact "float extent of at least
        # 1 px" shape `Box.rounded`'s correction exists for.
        rect = Box(cx - width / 2, cy - height / 2, width, height).rounded(min_1px=min_1px)
        if element.filled:
            return PlacedShape(element, rect, (round(cx), round(cy)), depth,
                               corner_radius=corner, thickness=max(1, thickness))
        # An unfilled rectangle is stroked *on* its edge, so the ink straddles
        # the declared rectangle the same way a circle's outline straddles its
        # radius -- see `PlacedShape.rect`.
        pad = max(1, thickness) // 2 + 1
        reach = Box(rect.x - pad, rect.y - pad,
                    rect.width + 2 * pad, rect.height + 2 * pad).rounded()
        return PlacedShape(element, reach, (round(cx), round(cy)), depth,
                           corner_radius=corner, thickness=max(1, thickness), rect=rect)

    def _resolve_text(self, element: Text, parent: Box, depth: int) -> Placed:
        font_px, reference, is_custom, baked, metric = self._font_for(element)
        font_is_vector = False
        font_face = ""
        font_available = True
        if is_custom:
            spec = self.face.fonts[element.font]
            if spec.is_vector:
                # `baked`/`metric` from `_font_for` are both meaningless for a
                # vector font: `self.fonts` (baked sheets) never holds one --
                # `wfb.emit.resources.bake_fonts` only rasterises `is_baked`
                # entries -- and `_font_for_ref`'s `metric` is always `None`
                # for *any* custom font. Both are replaced below with the
                # real per-device answer.
                font_is_vector = True
                baked = None
                font_face, font_available = self._resolve_vector_face(spec, element.curve)
                metric = self._vector_font_metric(font_face, font_px)
        widest = self._widest_text(element)
        if baked is not None:
            width, line_height = baked.measure(widest)
            estimated = False
        else:
            # A system font, or a vector font (`metric` synthesised just
            # above): the device publishes its pixel height but not its
            # per-glyph advances. Measure the device's own real typeface when
            # `wfb.fonts.fetch_system` can locate one (the user's own Garmin
            # font root, or a pinned free stand-in), scaled to the device's
            # own published metrics -- still an estimate (a `substitute`/
            # `none` match draws a different family's shape, and even an
            # `exact` match's free release can differ in hinting/kerning),
            # and still labelled as one. An *unavailable* vector font's
            # `metric` names no real face at all, so this falls all the way
            # to Pillow's own bundled default, scaled to `font_px` -- still a
            # conservative, non-zero estimate (plan 11 §4), never an
            # optimistic empty box, even though nothing draws here at runtime.
            width, _ = fallback.measure(widest, metric) if metric else (0, False)
            line_height = fallback.line_height(metric) if metric else font_px
            estimated = True

        x, y = self._point(element.at, parent)
        justify = self._justify(element)

        curve = element.curve
        curve_style = curve.style if curve is not None else None
        curve_angle_degrees = curve.angle.degrees if curve is not None else 0.0
        curve_angle_garmin = (garmin_curve_angle(curve_style, curve.angle)
                              if curve is not None else 0.0)
        curve_radius_px = 0
        curve_direction = curve.direction if curve is not None else None
        if curve_style == "radial" and curve.radius is not None:
            curve_radius_px = round(self._len(curve.radius, parent, Axis.MINOR, 0))

        if curve_style == "angled":
            # The rotated bounding box of the measured extent about the
            # anchor (plan 11 §4) -- conservative, never optimistic: it is
            # the box of the whole `width`x`line_height` rectangle turned by
            # the angle the device actually draws at, not the tighter box
            # the real glyph ink would occupy.
            box = self._rotated_text_box(x, y, width, line_height,
                                         element.align, element.vertical_align,
                                         curve_angle_garmin)
        elif curve_style == "radial":
            # The tight arc-shaped box (2026-09-21 follow-up to plan 11 §4):
            # a SQUARE centred on the circle over-reports badly on a round
            # screen -- its corners sit at (radius + line_height) * sqrt(2)
            # from centre, well outside the panel, even when every glyph is
            # comfortably inside (confirmed on the real simulator and in
            # `wfb preview`, `docs/research/probes/vector-fonts/
            # radial-facing-both-directions.png`: nothing in
            # `examples/features/vector-text/face.yaml` actually overflows).
            # Bound the ink the run actually puts down instead: an annulus
            # sector over the angular range `radial_text_angle_span` derives
            # (the same per-glyph placement model `wfb.preview.
            # _draw_radial_vector_text` draws with, so the lint box and the
            # preview cannot silently disagree about where the text sits),
            # at radii `radius -/+ line_height`. That radial band is
            # conservative, not tight: each glyph's own vertical shift off
            # the baseline circle is at most `line_height / 2`
            # (`alignment_shift`'s `top`/`bottom` cases), so a full
            # `line_height` on both sides is already slack, never a
            # closest-fit estimate. `(x, y)` is already the circle's own
            # centre here (`Text.curve`'s `at:` reinterpretation, §2.2).
            if curve_radius_px > 0:
                theta_a, theta_b = radial_text_angle_span(
                    curve_angle_garmin, curve_direction, element.align, width, curve_radius_px)
                box = arc_bbox(x, y, curve_radius_px - line_height, curve_radius_px + line_height,
                               theta_a, theta_b)
            else:
                # No usable radius -- schema requires `radius:` > 0 with
                # `style: radial`, so this is unreachable in practice, but
                # stay conservative rather than divide by zero.
                reach = curve_radius_px + line_height
                box = Box(x - reach, y - reach, 2 * reach, 2 * reach)
        else:
            # The lint box only -- the runtime `drawText` anchor stays `(x, y)`
            # unshifted: a glyph kind's alignment is a device-side justify, not
            # a build-time box move. `bottom` puts this box's top at
            # `y - line_height`, matching the actual draw call and the preview.
            dx, dy = alignment_shift(width, line_height, element.align, element.vertical_align)
            box = Box(x + dx - width / 2, y + dy - line_height / 2, width, line_height)

        return PlacedText(
            element, box.rounded(), (round(x), round(y)), depth,
            anchor_point=(round(x), round(y)),
            justify=justify,
            font_reference=reference,
            font_is_custom=is_custom,
            font_px=font_px,
            font_metric=metric,
            widest=widest,
            measured_width=round(width),
            width_is_estimated=estimated,
            font_face=font_face,
            font_is_vector=font_is_vector,
            font_available=font_available,
            curve_style=curve_style,
            curve_angle_degrees=curve_angle_degrees,
            curve_angle_garmin=curve_angle_garmin,
            curve_radius_px=curve_radius_px,
            curve_direction=curve_direction,
        )

    def _vector_gate1_ok(self, curve_style: str | None) -> bool:
        """Gate 1 (`docs/research/12-vector-fonts.md` §3): does this device
        even have `Graphics.getVectorFont` -- and, under `curve:`, the
        matching `Dc.drawAngledText`/`Dc.drawRadialText` -- at all?

        Checked independently per plan 11 §1's own caution: the three move
        together on every device installed for this project (verified
        2026-09-20), but nothing in the SDK promises that holds for the
        full 164-device fleet, so an upright `face:` text only ever needs
        `getVectorFont` itself, never the draw call it happens not to use.
        """
        device = self.device
        if not device.has_symbol(Device.VECTOR_FONT_SYMBOL):
            return False
        if curve_style == "angled" and not device.has_symbol(Device.DRAW_ANGLED_TEXT_SYMBOL):
            return False
        if curve_style == "radial" and not device.has_symbol(Device.DRAW_RADIAL_TEXT_SYMBOL):
            return False
        return True

    def _resolve_vector_face(self, spec: FontSpec, curve: "Curve | None") -> tuple[str, bool]:
        """Gates 1-3 (plan 11 §1) for one `face:` `FontSpec`, on this
        device: `("", False)` when gate 1 fails (`_vector_gate1_ok`) or
        none of `spec.face`'s author-ordered candidates is one of this
        device's own :attr:`~wfb.devices.Device.scalable_faces` (gates 2/3);
        otherwise the *first* candidate this device actually publishes and
        `True` -- the one resolved face codegen emits as `:face` (plan 11
        §2.1: never the array, since a runtime array pick could not be
        measured against or named in an error).

        `wfb.lint.check_vector_font_availability` is what turns a `("",
        False)` here into a build error or a suppressible warning, once
        every target device has been resolved -- this method only ever
        answers for the one device `self` was built for (`Resolver.__init__`),
        never the whole build.
        """
        if not self._vector_gate1_ok(curve.style if curve is not None else None):
            return "", False
        for name in spec.face:
            if name in self.device.scalable_faces:
                return name, True
        return "", False

    def _vector_font_metric(self, face_name: str, font_px: int) -> FontMetric:
        """A synthetic `FontMetric` for a resolved (or unavailable) vector
        face, so `wfb.fonts.fallback.measure`/`line_height` -- the one
        measurement path this compiler has, plan 11 §4 -- can estimate a
        vector font's extent exactly the way they already estimate a system
        font's: `metric.font` is the real on-disk stem
        (`Device.scalable_face_files`), which is what both
        `wfb.fonts.fetch_system.garmin_font_root`'s exact-stem match and
        `wfb/fonts/registry.json`'s own `names` table key on -- not
        `face_name` (the `:face` string, `"RobotoCondensedBold"`), which
        neither matches directly (confirmed against an installed device:
        the `filename` is `"RobotoCondensed-Bold"`).

        `face_name` empty (gates 1-3 failed) synthesises a metric that
        locates nothing at all (`font=""`) -- `fallback.system_face` falls
        back to Pillow's own bundled default scaled to `font_px`, a
        conservative non-zero estimate rather than a crash or a silent
        zero (see `_resolve_text`'s own note on this).  `size_px=font_px`
        is always this font's own resolved `:size` in pixels
        (`FontSpec.pixel_size`, already computed as `font_px` by
        `Resolver._font_for_ref`'s `_unbaked_font_size` path) -- a vector
        font has no separate "published line height" the way a `FONT_*`
        symbol does, so the one pixel size doubles as both.
        """
        filename = self.device.scalable_face_files.get(face_name, face_name)
        return FontMetric(symbol=face_name or "vector", face=face_name, font=filename,
                          size_px=font_px)

    @staticmethod
    def _rotated_text_box(
        x: float, y: float, width: float, height: float, align: str, vertical_align: str,
        garmin_angle_degrees: float,
    ) -> Box:
        """`curve: {style: angled}`'s lint box (plan 11 §4): the axis-aligned
        bounding box of the `width`x`height` text box, rotated about the
        anchor `(x, y)` by `garmin_angle_degrees` -- Garmin's own convention
        (`Curve.angle.to_garmin()`), because that is the rotation the device
        actually draws (verified against `$CIQ_SDK/samples/TrueTypeFonts/
        source/MenuItems/TrueTypeFontsAngledText.mc`: at Garmin angle 0 the
        text is unrotated, reading left to right exactly like plain
        `drawText`, and the on-screen rotation direction it demonstrates --
        `tx = radius*cos(rad), ty = radius*-sin(rad)` -- is standard
        math-convention rotation applied directly to screen coordinates).

        `align`/`vertical_align` still shift the box the same way
        `alignment_shift` shifts an ordinary upright text's lint box (plan
        11 §2.3: the *runtime* anchor never moves, device-side justify
        only) -- computed in the text's own unrotated baseline frame first,
        then rotated along with the rest of the box, so the shift turns
        with the text instead of staying screen-aligned.
        """
        theta = math.radians(garmin_angle_degrees)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        dx, dy = alignment_shift(width, height, align, vertical_align)
        cx = x + dx * cos_t + dy * sin_t
        cy = y - dx * sin_t + dy * cos_t
        hw, hh = width / 2.0, height / 2.0
        xs: list[float] = []
        ys: list[float] = []
        for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
            xs.append(cx + lx * cos_t + ly * sin_t)
            ys.append(cy - lx * sin_t + ly * cos_t)
        return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def _resolve_progress(self, element: Progress, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        min_1px = element.resolved_min_1px
        if element.style == "arc":
            radius = round(self._extent(element.radius, parent, Axis.MINOR, 0,
                                        min_1px=min_1px, what="radius"))
            thickness = max(1, round(self._extent(element.thickness, parent, Axis.MINOR, 1,
                                                  min_1px=min_1px, what="thickness")))
            # The author's clockwise-positive angle becomes Garmin's
            # counter-clockwise one; a positive sweep therefore draws clockwise
            # on the device.  `shape: arc` calls the same helper.
            box, cx, cy, start, sweep, garmin_start, direction = _arc_box(
                radius, thickness, cx, cy, element.align, element.vertical_align,
                element.start_angle, element.sweep)
            return PlacedProgress(
                element, box, (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start,
                garmin_direction=direction,
            )
        width, height, cx, cy = self._sized_shift(
            element.size, parent, cx, cy, element.align, element.vertical_align, min_1px=min_1px)
        box = Box(cx - width / 2, cy - height / 2, width, height)
        return PlacedProgress(element, box.rounded(min_1px=min_1px), (round(cx), round(cy)), depth,
                              size=(round(width), round(height)))

    def _resolve_icon(self, element: IconElement, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        # Independent of `parent`, deliberately: an icon's font is baked once,
        # before any box in the tree is resolved, so its size cannot depend on
        # one (ADR-equivalent reasoning in wfb.units.pixel_size).
        px = units.pixel_size(element.size, self.device.minor_radius)
        if element.is_dynamic:
            # The real glyph is chosen on-device at runtime (WfbWeather.mc);
            # measure and preview against the same representative glyph
            # `bake_size` used, which is guaranteed to be in this font.
            glyph_key = icons.DYNAMIC_WEATHER_TAG
            measure_codepoint = icons.WEATHER_BAKE_REFERENCE_GLYPH
        else:
            glyph_key = measure_codepoint = element.codepoint
        key = icons.font_key(element.size, glyph_key, element.resolved_antialias)
        font = self.fonts.get(key)
        if font is not None:
            width, height = font.measure(measure_codepoint)
        else:
            width = height = px  # the font failed to bake; keep a plausible box
        justify = self._justify(element)
        # The lint box only -- like `_resolve_text`, the runtime `drawText`
        # anchor stays `(cx, cy)` unshifted: an icon's alignment is a
        # device-side justify, not a build-time box move (see
        # `wfb.emit.monkeyc._emit_icon`).
        dx, dy = alignment_shift(width, height, element.align, element.vertical_align)
        box = Box(cx + dx - width / 2, cy + dy - height / 2, width, height)
        return PlacedIcon(
            element, box.rounded(), (round(cx), round(cy)), depth,
            size=px, font_key=key, codepoint=measure_codepoint,
            anchor_point=(round(cx), round(cy)),
            justify=justify,
        )

    def _resolve_graph(self, element: Graph, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        min_1px = element.resolved_min_1px
        width, height, cx, cy = self._sized_shift(
            element.size, parent, cx, cy, element.align, element.vertical_align, min_1px=min_1px)
        box = Box(cx - width / 2, cy - height / 2, width, height)
        thickness = max(1, round(self._extent(element.thickness, parent, Axis.MINOR, 2,
                                              min_1px=min_1px, what="thickness")))
        bar_width = max(1, round(self._extent(element.bar_width, parent, Axis.MINOR, 3,
                                              min_1px=min_1px, what="bar_width")))
        return PlacedGraph(
            element, box.rounded(min_1px=min_1px), (round(cx), round(cy)), depth,
            thickness=thickness, bar_width=bar_width, size=(round(width), round(height)),
        )

    def _resolve_complication_slot(self, element: ComplicationSlot, parent: Box,
                                   depth: int) -> Placed:
        """Resolve a `complication_slot`: an estimated box, plus the icon and
        text font resources the emitter needs.

        Unlike every other element, nothing about *what* is drawn is known
        here -- the wearer's pick is a runtime `Complications.Id`.  So this
        resolves only what a font baking, and the geometry lints, need
        ahead of time: the text font/estimated extent (`_complication_slot_
        widest`, the same "widest plausible rendering" idea `_widest_text`
        already uses), and -- when `icon_size:` is set -- one shared,
        multi-glyph icon font covering every icon `slot.icons` can resolve
        (the declared choices plus any per-choice override, or, for
        `choices: any`, the whole of `wfb.icons.COMPLICATION_ICON`), keyed
        by this slot's own name so two different slots never collide into
        one font resource.

        The estimated box's extent, for any `icon_position:`, comes from
        `complication_slot_pair_geometry` -- the one place this geometry is
        computed -- using `icon_px` (the *declared* visual
        icon height, not the measured glyph height) as the icon's height,
        matching the `left`-position height estimate
        (`max(line_height, icon_px, 1)`) so a design that never sets
        `icon_position:`/`icon_gap:` generates the same numbers as one that
        only ever used `left`.
        """
        cx, cy = self._point(element.at, parent)
        font_px, reference, is_custom, baked, metric = self._font_for(element)
        widest = self._complication_slot_widest(element)
        if baked is not None:
            text_width, line_height = baked.measure(widest)
        else:
            text_width, _ = fallback.measure(widest, metric) if metric else (0, False)
            line_height = fallback.line_height(metric) if metric else font_px

        icon_font_key: str | None = None
        icon_px = 0
        icon_width = 0
        if element.icon_size is not None:
            slot = self.face.config_data.get(element.slot)
            reference_glyph: str | None = None
            if slot is not None:
                mapped = slot.icons
                if mapped:
                    default_icon = mapped.get(slot.default)
                    reference_icon = default_icon or sorted(mapped.values(), key=lambda si: si.key)[0]
                    reference_glyph = reference_icon.codepoint
            if reference_glyph is not None:
                icon_px = units.pixel_size(element.icon_size, self.device.minor_radius)
                icon_font_key = icons.font_key(
                    element.icon_size, f"slot_{element.slot}", element.resolved_antialias)
                font = self.fonts.get(icon_font_key)
                if font is not None:
                    icon_width, _ = font.measure(reference_glyph)
                else:
                    icon_width = icon_px

        gap_px = (units.pixel_size(element.icon_gap, self.device.minor_radius)
                 if element.icon_gap is not None else COMPLICATION_SLOT_ICON_GAP)
        geometry = complication_slot_pair_geometry(
            element.icon_position,
            icon_width if icon_font_key else 0, icon_px if icon_font_key else 0,
            text_width, line_height, gap_px,
        )
        height = max(geometry.height, 1)
        # The estimated box only -- like a glyph kind's lint box, the runtime
        # anchor (`anchor_point` below) stays `(cx, cy)` unshifted: the pair
        # is centred on the wearer's actual pick at runtime, in
        # `wfb.emit.monkeyc._emit_complication_slot`'s own arithmetic, not
        # here.
        dx, dy = alignment_shift(geometry.width, height, element.align, element.vertical_align)
        box = Box(cx + dx - geometry.width / 2, cy + dy - height / 2, geometry.width, height)
        return PlacedComplicationSlot(
            element, box.rounded(), (round(cx), round(cy)), depth,
            anchor_point=(round(cx), round(cy)),
            font_reference=reference, font_is_custom=is_custom, font_px=font_px,
            font_metric=metric,
            widest=widest, icon_font_key=icon_font_key, icon_px=icon_px,
            icon_position=element.icon_position, icon_gap_px=gap_px,
        )

    def _complication_slot_widest(self, element: ComplicationSlot) -> str:
        """The widest plausible reading a `complication_slot` can draw.

        There is no per-choice `format:` to size against (`Builder._build_
        complication_slot` forbids it, because the value's concrete type
        genuinely varies by choice) -- so this estimates across *every*
        declared choice rather than exactly for one, the same digit-count
        estimate `formatting.widest` already falls back to for a Number/
        Float/String source with no documented range (every complication
        type qualifies: none is in `wfb.formatting._SOURCE_DIGITS`).
        `label:`/`unit:` add unbounded, localised device strings on top --
        recorded approximately rather than precisely, the same "over-estimate
        costs a spurious warning, under-estimate costs a clipped face"
        tolerance this project already accepts for a Type.STRING source of
        unknown length.
        """
        slot = self.face.config_data.get(element.slot)
        choices: tuple[str, ...] = ()
        if slot is not None:
            choices = (slot.default,) if slot.allow_any else slot.choices
        widest = ""
        for name in choices:
            ctype = complications.TYPES.get(name)
            if ctype is None:
                continue
            value_type = Type.STRING if ctype.value_type == "string" else Type.NUMBER
            candidate = formatting.widest("{}", None, value_type)
            widest = _longer(widest, candidate)
        if element.when_absent == "placeholder" and element.placeholder:
            widest = _longer(widest, element.placeholder)
        # `label:`/`unit:` are deliberately NOT folded in here, unlike the
        # digit-count estimate above: `Complication.shortLabel`/`.longLabel`
        # and a String `.unit` are localised device strings with no
        # documented upper bound at all (unlike a digit count, which at
        # least has a plausible ceiling), so *any* fixed padding here is a
        # guess that would either be routinely wrong or -- picked large
        # enough to rarely be wrong -- inflate every ordinary slot's box
        # into a spurious `off-screen` warning (checked directly: an
        # 8-character placeholder pushed a design that fits comfortably
        # off the framebuffer). `docs/limitations.md` records this as a
        # documented gap instead: the geometry/overflow checks size a
        # slot's box from its value alone.
        return widest

    def _resolve_hands(self, element: HandsElement, parent: Box, depth: int) -> Placed:
        """`type: hands` -- the axis, plus every part of every declared hand
        resolved to whole pixels in the hand's own frame.  The rotation
        itself is the one piece of layout arithmetic the *device* performs
        (ADR 0004, amended) -- everything here is still a build-time
        constant.
        """
        cx, cy = self._point(element.at, parent)
        hand_set = self.face.hands[element.hands]
        resolved: dict[str, ResolvedHand] = {}
        reach = 0.0
        for name, hand in hand_set.hands():
            if name == "second" and element.seconds == "never":
                # The set's second hand is not drawn at all -- left
                # unresolved, exactly as if the set declared no `second:` at
                # all, so codegen's `if hand is None: continue` already
                # covers it with no extra check, and its geometry does not
                # inflate the swept disc's reach (only a *drawn* hand's ink
                # counts).
                continue
            parts = []
            for part_index, part in enumerate(hand.parts):
                # `<id>.<hand>.parts[<i>]`, not `<id>.parts[<i>]`: a hand set
                # has up to three independent `parts:` lists, so the plain
                # element id would name the hour hand's first part and the
                # minute hand's first part identically -- and a
                # `sub-pixel-length` finding that cannot say *which* hand it
                # is about sends the author to the wrong line.  A pattern has
                # exactly one `parts:` list, so `_resolve_pattern` needs no
                # such qualifier and keeps the bare id.
                resolved_part, part_reach = self._resolve_hand_part(
                    part, f"{element.id}.{name}", part_index,
                    min_1px=element.resolved_min_1px)
                parts.append(resolved_part)
                reach = max(reach, part_reach)
            resolved[name] = ResolvedHand(parts=tuple(parts))
        axis = (round(cx), round(cy))
        box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
        return PlacedHands(
            element, box.rounded(), axis, depth,
            hour=resolved.get("hour"), minute=resolved.get("minute"),
            second=resolved.get("second"), reach=reach,
        )

    def _resolve_hand_part(
        self, part, element_id: str = "", part_index: int = -1, *, min_1px: bool,
    ) -> tuple[ResolvedHandPart, float]:
        """One hand part -> whole-pixel geometry in the hand's own frame,
        plus its own reach from the axis (the farthest ink any of its
        drawing touches).  Rounds with :func:`round_half_away`, not the plain
        `round()` every other element here uses -- a mirror-symmetry
        rule specific to a hand frame, which is the only geometry a
        symmetric pair of authored coordinates (`dx: -1.5px`/`dx: 1.5px`)
        can appear in.

        `element_id`/`part_index` name the part for two independent reasons:
        a `shape: text` part's `_font_for_ref` "no pixel metrics"
        warning (reachable only through a pattern's template,
        never a hand's -- `wfb.ir.HAND_PART_REJECTED_SHAPES` still refuses
        it), and every part's own `SubPixelLength`
        owner id (`_owner_id`, below), which every shape can reach.  Both
        callers (`_resolve_hands`, `_resolve_pattern`) always pass real
        values.

        `min_1px` is the *inherited* value from the owning element
        (`element.resolved_min_1px`) -- combined with this part's own
        authored override, if any, into `effective_min_1px` below exactly
        the way `Builder._resolve_inherited_flag` combines an element's with
        its group's, except this happens once per element *instance* rather
        than once in the IR: `HandPart.min_1px` has no `resolved_` twin,
        because one `hands:` set can be placed by more than one `type:
        hands` element, and two placements can resolve `min_1px`
        differently (see that field's docstring).
        """
        owner_id = f"{element_id}.parts[{part_index}]" if part_index >= 0 else element_id
        self._owner_id = owner_id
        self._owner_span = part.span
        effective_min_1px = part.min_1px if part.min_1px is not None else min_1px

        if part.shape == "polygon":
            points = tuple(
                (round_half_away(x), round_half_away(y))
                for x, y in (self._hand_point(p) for p in part.points)
            )
            reach = max((math.hypot(x, y) for x, y in points), default=0.0)
            return ResolvedHandPart("polygon", part.color, points=points), reach

        if part.shape == "rectangle":
            cx, cy = self._hand_point(part.at)
            width = self._hand_extent(part.size.width,
                                      min_1px=effective_min_1px, what="size.width")
            height = self._hand_extent(part.size.height,
                                       min_1px=effective_min_1px, what="size.height")
            # The placement box is the declared `size:`, in the part's own
            # frame -- shift the centre
            # before the corners (and `round_half_away`) below, the same order
            # `Resolver._resolve_shape` already uses in the parent's frame.
            # `top`/`left` mean `-y`/`-x` here too: a hand's 12 o'clock rest
            # pose is already `-y`, so no sign flip is needed to match the
            # "towards 12 o'clock" convention.
            dx, dy = alignment_shift(width, height, part.align, part.vertical_align)
            cx, cy = cx + dx, cy + dy
            hw, hh = width / 2.0, height / 2.0
            # top-left, top-right, bottom-right, bottom-left -- the same
            # corner order a rotated rectangle keeps no matter which corner
            # ends up where once the device rotates it.
            corners = [
                (cx - hw, cy - hh), (cx + hw, cy - hh),
                (cx + hw, cy + hh), (cx - hw, cy + hh),
            ]
            points = tuple((round_half_away(x), round_half_away(y)) for x, y in corners)
            reach = max(math.hypot(x, y) for x, y in points)
            return ResolvedHandPart("polygon", part.color, points=points), reach

        if part.shape == "line":
            x1, y1 = self._hand_point(part.at)
            x2, y2 = self._hand_point(part.to)
            thickness = max(1, round_half_away(self._hand_extent(
                part.thickness, default=1, min_1px=effective_min_1px, what="thickness")))
            reach = max(math.hypot(x1, y1), math.hypot(x2, y2)) + thickness / 2.0
            return ResolvedHandPart(
                "line", part.color,
                x1=round_half_away(x1), y1=round_half_away(y1),
                x2=round_half_away(x2), y2=round_half_away(y2),
                thickness=thickness,
            ), reach

        if part.shape == "arc":
            # A hand never produces this shape (rejected in `wfb.ir`); a
            # pattern's template does.  Always centred on the
            # origin (x=y=0), so its reach is exactly the pen's own
            # extent -- no `at:` to add a distance-from-origin term.
            radius = round_half_away(self._hand_extent(
                part.radius, min_1px=effective_min_1px, what="radius"))
            thickness = max(1, round_half_away(self._hand_extent(
                part.thickness, default=1, min_1px=effective_min_1px, what="thickness")))
            start_angle = (part.start_angle or Angle(0.0)).degrees
            sweep = (part.sweep or Angle(360.0)).degrees
            reach = radius + thickness / 2.0
            return ResolvedHandPart(
                "arc", part.color, x=0, y=0, radius=radius, thickness=thickness,
                start_angle=start_angle, sweep=sweep,
            ), reach

        if part.shape == "text":
            # A pattern's template only (`wfb.ir.HAND_PART_REJECTED_SHAPES`
            # keeps this off a hand) -- upright glyphs, so the anchor is the
            # only thing that goes through `_hand_point`; the glyphs
            # themselves are measured, not rotated (unless `curve:` turns
            # them too -- plan 11 slice 2, below). `reach` is always `0.0`
            # here: text is not rotation-invariant, so `Resolver.
            # _resolve_pattern`'s per-copy loop computes the real farthest
            # corner instead.
            x0, y0 = self._hand_point(part.at)
            x, y = round_half_away(x0), round_half_away(y0)
            font_px, reference, is_custom, baked, metric = self._font_for_ref(
                part.font, part.font_is_custom, owner_id)
            font_is_vector = False
            font_face = ""
            font_available = True
            if is_custom:
                spec = self.face.fonts[part.font]
                if spec.is_vector:
                    # The exact same override `_resolve_text` applies once
                    # `_font_for` says the reference is custom (plan 11 §4:
                    # `baked`/`metric` from `_font_for_ref` are both
                    # meaningless for a vector font) -- one face-resolution
                    # path, reused here rather than duplicated.
                    font_is_vector = True
                    baked = None
                    font_face, font_available = self._resolve_vector_face(spec, part.curve)
                    metric = self._vector_font_metric(font_face, font_px)
            if baked is not None:
                widths = tuple(baked.measure(t)[0] for t in part.texts)
                line_height = baked.line_height
            elif metric is not None:
                widths = tuple(fallback.measure(t, metric)[0] for t in part.texts)
                line_height = fallback.line_height(metric)
            else:
                widths = tuple(0 for _ in part.texts)
                line_height = font_px
            justify = self._justify(part)
            curve = part.curve
            curve_style = curve.style if curve is not None else None
            curve_angle_degrees = curve.angle.degrees if curve is not None else 0.0
            curve_angle_garmin = (garmin_curve_angle(curve_style, curve.angle)
                                  if curve is not None else 0.0)
            curve_radius_px = 0
            curve_direction = curve.direction if curve is not None else None
            if curve_style == "radial" and curve.radius is not None:
                # `curve.radius` is a `handLength` (px/%r only -- schema
                # `patternCurve`), resolved the same way every other
                # pattern-part radius/thickness is: `_hand_extent`, so a
                # relative one also gets the `min_1px`/sub-pixel-length
                # treatment a circle or arc part's own `radius:` already
                # gets, not a silent, unrecorded rounding.
                curve_radius_px = round_half_away(self._hand_extent(
                    curve.radius, min_1px=effective_min_1px, what="curve.radius"))
            return ResolvedHandPart(
                "text", part.color, x=x, y=y,
                font_reference=reference, font_is_custom=is_custom, font_px=font_px,
                font_metric=metric,
                font_face=font_face, font_is_vector=font_is_vector,
                font_available=font_available,
                justify=justify, align=part.align, vertical_align=part.vertical_align,
                line_height=line_height, texts=part.texts, widths=widths,
                curve_style=curve_style, curve_angle_degrees=curve_angle_degrees,
                curve_angle_garmin=curve_angle_garmin, curve_radius_px=curve_radius_px,
                curve_direction=curve_direction,
            ), 0.0

        # circle
        cx, cy = self._hand_point(part.at)
        radius = round_half_away(self._hand_extent(
            part.radius, min_1px=effective_min_1px, what="radius"))
        # The placement box is the full `2*radius` square,
        # at the resolved (already-rounded) radius the part draws with --
        # shifted before `reach`/`round_half_away` below, same as
        # `Resolver._resolve_shape`'s circle branch in the parent's frame.
        dx, dy = alignment_shift(2 * radius, 2 * radius, part.align, part.vertical_align)
        cx, cy = cx + dx, cy + dy
        thickness = max(1, round_half_away(self._hand_extent(
            part.thickness, default=1, min_1px=effective_min_1px, what="thickness")))
        pen_reach = radius if part.filled else radius + thickness / 2.0
        reach = math.hypot(cx, cy) + pen_reach
        return ResolvedHandPart(
            "circle", part.color,
            x=round_half_away(cx), y=round_half_away(cy), radius=radius,
            thickness=thickness, filled=part.filled,
        ), reach

    def _resolve_pattern(self, element: PatternElement, parent: Box, depth: int) -> Placed:
        """`type: pattern` -- the template resolved once, in its own frame
        (`_resolve_hand_part`, reused: a pattern part is authored exactly
        like a hand part), plus which copies are drawn and the
        repeat rule.  The repeat transform itself -- turning or stepping the
        template -- is the one piece of layout arithmetic the device
        performs (ADR 0004, amended a second time), same bargain as hands.

        Radial's `reach` is rotation-invariant (distance from the centre of
        rotation is unchanged by rotating about it), so it comes straight
        from the per-part reach `_resolve_hand_part` already returns, the
        same shortcut `_resolve_hands` takes -- independent of which copies
        are actually drawn, since every drawn copy shares one template.
        `box`, unlike `reach`, really does depend on which copies draw and
        where, so it is computed by applying :meth:`PlacedPattern.transform`
        to every drawn copy's ink.

        A `shape: text` part breaks the "rotation-invariant" half of that
        shortcut: upright glyphs are not the same distance
        from the centre at every angle, so `_resolve_hand_part` always
        returns `0.0` reach for one, and the real farthest corner of any
        *drawn* copy's text box is instead folded into the per-copy ink loop
        below, alongside `box` -- the one other quantity that already has to
        look at drawn copies individually.
        """
        cx, cy = self._point(element.at, parent)
        center = (round(cx), round(cy))

        parts: list[ResolvedHandPart] = []
        reach = 0.0
        for part_index, part in enumerate(element.parts):
            resolved_part, part_reach = self._resolve_hand_part(
                part, element.id, part_index, min_1px=element.resolved_min_1px)
            parts.append(resolved_part)
            reach = max(reach, part_reach)

        if element.pattern == "radial":
            start, step = element.start_angle, element.step_angle
            dx = dy = 0
        else:
            start = step = 0.0
            reach = 0.0  # only a radial pattern reports a disc
            step_position = element.step or Position()
            dx = round_half_away(self._len(step_position.dx, parent, Axis.X, 0))
            dy = round_half_away(self._len(step_position.dy, parent, Axis.Y, 0))

        placed = PlacedPattern(
            element, IntBox(0, 0, 0, 0), center, depth,
            parts=tuple(parts), copies=element.drawn_indices(),
            start=start, step=step, dx=dx, dy=dy, reach=reach,
        )

        min_x = min_y = math.inf
        max_x = max_y = -math.inf
        text_reach = 0.0
        cx_f, cy_f = float(center[0]), float(center[1])
        for index in placed.copies:
            ox, oy, sin_t, cos_t = placed.transform(index)
            # Copy `index`'s own rotation, design degrees clockwise from 12
            # -- `0.0` for a linear pattern, which never turns (`start`/
            # `step` are both `0.0` there, set just above). A curved text
            # part's box composes its own local `curve_angle_garmin` with
            # this (plan 11 slice 2, `_pattern_part_ink`'s own docstring);
            # every other shape ignores the argument.
            copy_angle_degrees = start + index * step
            for part in parts:
                lo_x, lo_y, hi_x, hi_y = _pattern_part_ink(
                    part, ox, oy, sin_t, cos_t, index, copy_angle_degrees)
                min_x, min_y = min(min_x, lo_x), min(min_y, lo_y)
                max_x, max_y = max(max_x, hi_x), max(max_y, hi_y)
                if part.shape == "text" and element.pattern == "radial":
                    for corner_x, corner_y in (
                        (lo_x, lo_y), (lo_x, hi_y), (hi_x, lo_y), (hi_x, hi_y),
                    ):
                        text_reach = max(text_reach, math.hypot(corner_x - cx_f, corner_y - cy_f))
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

    def _hand_point(self, at: Position) -> tuple[float, float]:
        """A part position within a hand's own frame -- there is no anchor
        and no parent box, only the axis (origin) and, for a polar position,
        the same clockwise-from-12 convention every other polar position
        uses (`_point`, which this deliberately does not call: that one
        starts from `parent.anchor_point`, and a hand frame has no box to
        anchor to at all)."""
        if at.is_polar:
            radius = self._hand_len(at.radius)
            theta = math.radians(at.angle.degrees)
            return radius * math.sin(theta), -radius * math.cos(theta)
        return self._hand_len(at.dx), self._hand_len(at.dy)

    def _hand_len(self, length: Length | None, default: float = 0) -> float:
        """Resolve a hand-frame length: px or %r only (schema-enforced), so
        neither the parent box nor a font is ever consulted."""
        if length is None:
            return float(default)
        return length.resolve(box=_HAND_FRAME_BOX, axis=Axis.MINOR,
                              minor_radius=self.minor_radius)

    def _hand_extent(self, length: Length | None, default: float = 0, *,
                     min_1px: bool, what: str) -> float:
        """:meth:`_hand_len`, then :func:`units.at_least_one_px` -- the hand-
        frame counterpart of :meth:`_extent`, for a hand/pattern part's own
        size, thickness or radius (never its `at:`/`to:`/polygon points).

        `min_1px`/`what` and the `SubPixelLength` recording below are the
        same contract `_extent` documents -- see that docstring; the only
        difference is whose `_owner_id`/`_owner_span` end up on the record:
        `_resolve_hand_part` narrows both to this part's own
        `<element id>.parts[<i>]` and span just before calling this, for
        every shape branch it has.
        """
        value = self._hand_len(length, default)
        if not min_1px and units.is_sub_pixel_length(length, value):
            self._record_sub_pixel(what, length, value)
        return units.at_least_one_px(length, value, min_1px)

    # -- helpers ----------------------------------------------------------

    def _point(self, at: Position, parent: Box) -> tuple[float, float]:
        ax, ay = parent.anchor_point(at.anchor)
        if at.is_polar:
            radius = self._len(at.radius, parent, Axis.MINOR, 0)
            theta = math.radians(at.angle.degrees)
            return ax + radius * math.sin(theta), ay - radius * math.cos(theta)
        dx = self._len(at.dx, parent, Axis.X, 0)
        dy = self._len(at.dy, parent, Axis.Y, 0)
        return ax + dx, ay + dy

    def _len(self, length: Length | None, parent: Box, axis: Axis, default: float,
             font_px: float | None = None) -> float:
        if length is None:
            return float(default)
        return length.resolve(box=parent, axis=axis, minor_radius=self.minor_radius,
                              font_px=font_px)

    def _extent(self, length: Length | None, parent: Box, axis: Axis, default: float,
                font_px: float | None = None, *, min_1px: bool, what: str) -> float:
        """:meth:`_len`, then :func:`units.at_least_one_px` -- for a length
        that is a *size, thickness or radius* rather than a position: a
        nonzero relative one clamps to at least 1 px when `min_1px` is true
        (see `at_least_one_px`'s own docstring for the "why a switch at all"
        reasoning). Every call site here that places rather than sizes an
        element (`at:`/`to:`/polygon points, a linear pattern's `step:`)
        stays on `_len` -- this only wraps the subset the docstring on
        `at_least_one_px` names.

        `min_1px` and `what` are both **required, with no default**: the
        first is the caller's own gate (almost always the owning element's
        `resolved_min_1px`), so a call site can never silently fall back to
        "off" by omission; the second names the authored key
        (`"size.width"`, `"size.height"`, `"thickness"`, `"bar_width"` or
        `"radius"`) for the `SubPixelLength` record below, so a missed call
        site cannot masquerade as a covered one under the wrong name.

        When `min_1px` is false and `length`/`value` is exactly the case
        :func:`units.is_sub_pixel_length` names -- a nonzero `%`/`%r` length
        that resolved under 1 px, so it would have been clamped had the
        switch been on -- this records one `SubPixelLength` against whichever
        element/part `_owner_id`/`_owner_span`/`_owner_element` currently
        name (`_resolve_list` sets them per element; `_resolve_hand_part`
        narrows the first two per part). That record is exactly what the
        suppressible `sub-pixel-length` lint reads; this is the one
        place in the resolver that can see the condition it needs, so it is
        also the one place responsible for capturing it.
        """
        value = self._len(length, parent, axis, default, font_px)
        if not min_1px and units.is_sub_pixel_length(length, value):
            self._record_sub_pixel(what, length, value)
        return units.at_least_one_px(length, value, min_1px)

    def _record_sub_pixel(self, key: str, length: Length | None, value: float) -> None:
        """Append one `SubPixelLength` for whatever `_extent`/`_hand_extent`
        just found -- see their docstrings for when that is. `length` is
        never actually `None` here (both callers only reach this branch
        after `units.is_sub_pixel_length` has already confirmed it is not),
        but the parameter stays optional so this matches `_extent`'s own
        `length` type rather than asserting a narrower one purely for this
        internal call.
        """
        assert length is not None
        assert self._owner_element is not None, "no element is being resolved yet"
        self.sub_pixel.append(SubPixelLength(
            owner=self._owner_id, key=key, length=length, value=value,
            span=self._owner_span, element=self._owner_element,
        ))

    def _unbaked_font_size(self, spec: FontSpec) -> int:
        """The size to assume for a custom font that was not baked.

        A real build always bakes every declared font, so this is the path a
        caller who resolved layout with an empty ``fonts`` dict takes -- a unit
        test, or a geometry-only pass.  `size:` is always a `Length`, and
        its unit already refers to this device, so it resolves exactly here.
        """
        return spec.pixel_size(self.minor_radius)

    def _font_for(self, element: Text) -> tuple[int, str, bool, BakedFont | None, FontMetric | None]:
        return self._font_for_ref(element.font, element.font_is_custom, element.id)

    def _font_for_ref(
        self, font: str, font_is_custom: bool, warn_id: str,
    ) -> tuple[int, str, bool, BakedFont | None, FontMetric | None]:
        """The shared body of `_font_for`, taking a bare `font:`/`font_is_
        custom` pair instead of a `Text` element -- what lets a `shape:
        text` pattern part (`Resolver._resolve_hand_part`)
        resolve its font through the exact same lookup and the exact same
        "no pixel metrics" warning `_font_for` already gives a `Text`
        element, with no second copy of either.

        The fifth element is the device's `FontMetric` for a system font
        (`None` for a custom one, and `None` when the device has no pixel
        metrics for this symbol at all) -- callers hand it straight to
        `wfb.fonts.fallback.measure`/`line_height` and carry it onto the
        `Placed`/`ResolvedHandPart` so `wfb.preview` measures and draws
        through the exact same face (plan 09 §4 R2.3).
        """
        if font_is_custom:
            baked = self.fonts.get(font)
            spec = self.face.fonts[font]
            return (baked.size if baked else self._unbaked_font_size(spec)), \
                font, True, baked, None
        metric = self.device.system_fonts.get(font)
        size = metric.size_px if metric else 0
        if metric is None:
            self.warnings.append(
                f"{warn_id}: no pixel metrics for {font} on {self.device.id}; "
                f"text extent is not checked"
            )
        return size, font, False, None, metric

    def _widest_text(self, element: Text) -> str:
        if element.literal is not None:
            return element.literal
        if element.value is None:
            return ""
        source = catalog.get(element.value.sources[0]) if element.value.sources else None
        spec = element.format or "{}"
        widest = formatting.widest(spec, source, element.value.value.type,
                                   element.value.scale)
        if element.when_absent == "placeholder" and element.placeholder:
            widest = _longer(widest, element.placeholder)
        if element.when_absent == "fallback" and element.fallback is not None:
            # 'fallback:' is drawn through the exact same format spec as the
            # real value (see _emit_text in wfb.emit.monkeyc), so its widest
            # rendering has to be considered too -- otherwise a font baked
            # from the *value*'s digit range alone can come up short for a
            # wider fallback (e.g. a longer literal string on a nullable
            # STRING source).
            widest = _longer(widest, _fallback_widest(element.fallback, spec))
        return widest

    @staticmethod
    def _justify(element: Text | HandPart | IconElement) -> tuple[str, ...]:
        """`Toybox.Graphics.TEXT_JUSTIFY_*` flags for anything with `.align`/
        `.vertical_align` -- a `Text` element, a `shape: text` pattern part,
        or an `IconElement`, all of which carry the same two fields under
        the same names.
        """
        flags = {
            "left": "TEXT_JUSTIFY_LEFT",
            "center": "TEXT_JUSTIFY_CENTER",
            "right": "TEXT_JUSTIFY_RIGHT",
        }[element.align]
        out = [flags]
        if element.vertical_align == "center":
            out.append("TEXT_JUSTIFY_VCENTER")
        return tuple(out)


def _longer(current: str, candidate: str) -> str:
    """`candidate` if it is strictly longer than `current`, else `current`
    unchanged -- "a placeholder/estimate longer than the widest-so-far
    wins," the one rule `_widest_text` (placeholder, fallback) and
    `Resolver._complication_slot_widest` (per-choice estimate, placeholder)
    each repeated as their own ``if len(x) > len(y): y = x``.
    """
    return candidate if len(candidate) > len(current) else current


def _fallback_widest(fallback_expr: Expression, spec: str) -> str:
    """The widest string a `fallback:` expression could render, through the
    same format spec the bound value uses (see `wfb.emit.monkeyc._emit_text`).

    A literal string fallback (`fallback: "N/A"`) renders exactly as written,
    the same way `placeholder:` already does above -- `formatting.widest`'s
    digit-based estimate has no way to guess the content of an arbitrary
    string, so a literal one is used verbatim.  Anything else (typically a
    numeric literal, or an expression over a non-nullable source) goes
    through the same digit-count estimate the bound value itself uses, keyed
    off the fallback's own source when it has one.
    """
    if fallback_expr.value.type is Type.STRING and fallback_expr.constant is not None:
        return str(fallback_expr.constant)
    source = catalog.get(fallback_expr.sources[0]) if fallback_expr.sources else None
    return formatting.widest(spec, source, fallback_expr.value.type, fallback_expr.scale)


def resolve(face: Face, device: Device, fonts: dict[str, BakedFont]) -> ResolvedFace:
    return Resolver(face, device, fonts).resolve()


#: How much of a round screen's outer edge the bezel effectively crops.
BEZEL_MARGIN = 0.02


def inside_screen(box: IntBox, device: Device) -> bool:
    """Is the box inside the framebuffer?

    Shape does not enter into this.  The framebuffer is rectangular on every
    device, including round ones -- a full-bleed background legitimately paints
    the corners even though they are never lit.  Visibility is a separate
    question, answered by :func:`inside_visible_area`.
    """
    return box.x >= 0 and box.y >= 0 and box.right <= device.width and box.bottom <= device.height


def circular_extent(placed: "Placed") -> tuple[float, float, float] | None:
    """``(cx, cy, radius)`` for an element that is genuinely round, else ``None``.

    A ring's *bounding box* has corners far outside the ring itself, so checking
    the box against a round screen would report every full-width arc as cropped.
    """
    if isinstance(placed, PlacedProgress) and placed.element.style == "arc":
        return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
    if isinstance(placed, PlacedShape) and placed.element.shape == "arc":
        return (placed.center[0], placed.center[1], placed.radius + placed.thickness / 2.0)
    if isinstance(placed, PlacedShape) and placed.element.shape == "circle":
        reach = placed.radius + (0 if placed.element.filled else placed.thickness / 2.0)
        return (placed.center[0], placed.center[1], reach)
    if isinstance(placed, PlacedHands):
        return (placed.center[0], placed.center[1], placed.reach)
    if isinstance(placed, PlacedPattern) and placed.element.pattern == "radial":
        return (placed.center[0], placed.center[1], placed.reach)
    return None


def inside_visible_area_for(placed: "Placed", device: Device) -> bool | None:
    """Visibility test that respects the element's actual shape."""
    circle = circular_extent(placed)
    if circle is None:
        return inside_visible_area(placed.box, device)
    if device.shape != "round":
        return inside_visible_area(placed.box, device)
    cx, cy, reach = circle
    screen_cx, screen_cy = device.width / 2, device.height / 2
    limit = device.minor_radius * (1.0 - BEZEL_MARGIN)
    return math.hypot(cx - screen_cx, cy - screen_cy) + reach <= limit + 0.5


def inside_visible_area(box: IntBox, device: Device) -> bool | None:
    """Is every corner of the box within the part of the screen the user sees?

    ``None`` means "not checked": ``semi-round`` and ``semi-octagon`` geometry is
    not established (ADR 0004), and a confident wrong answer is worse than none.
    """
    if device.shape == "round":
        cx, cy = device.width / 2, device.height / 2
        radius = device.minor_radius * (1.0 - BEZEL_MARGIN)
        corners = [(box.x, box.y), (box.right, box.y), (box.x, box.bottom), (box.right, box.bottom)]
        return all(math.hypot(x - cx, y - cy) <= radius + 0.5 for x, y in corners)
    if device.shape == "rectangle":
        return inside_screen(box, device)
    return None


def is_full_bleed(box: IntBox, device: Device) -> bool:
    """Does this element deliberately cover the whole framebuffer?

    A full-bleed background is *meant* to run past the visible disc, so it is
    exempt from the visible-area check rather than warning on every build.
    """
    return (box.x <= 0 and box.y <= 0
            and box.right >= device.width and box.bottom >= device.height)


def safe_area(device: Device) -> Box | None:
    """The region in which *any* element is guaranteed visible.

    This is the inscribed square, which is much stricter than
    :func:`inside_visible_area` -- it is what a layout heuristic would use to
    place something blindly, not what a specific resolved box is checked against.
    """
    if device.shape == "round":
        radius = device.minor_radius * (1.0 - BEZEL_MARGIN)
        side = radius * math.sqrt(2)
        return Box(device.width / 2 - side / 2, device.height / 2 - side / 2, side, side)
    if device.shape == "rectangle":
        return Box(0, 0, device.width, device.height)
    return None


__all__ = [
    "Placed", "PlacedShape", "PlacedText", "PlacedProgress", "PlacedIcon",
    "PlacedGraph", "PlacedComplicationSlot", "PlacedHands", "PlacedPattern",
    "ResolvedHand",
    "ResolvedHandPart",
    "ResolvedFace", "resolve", "safe_area", "inside_screen", "inside_visible_area",
    "inside_visible_area_for", "circular_extent", "garmin_arc", "garmin_curve_angle",
    "alignment_shift", "round_half_away",
    "is_full_bleed",
]
