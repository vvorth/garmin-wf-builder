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
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from . import kinds, units
from .devices import Device, FontMetric
from .diagnostics import Span
from .fonts import BakedFont, fallback
from .ir import (
    Curve, Element, Expression, Face, FontSpec, Graph, Group,
    HandPart, IconElement, Position, Progress, Shape,
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


#: The "parent box" of a hand/pattern part's own frame (`Resolver._hand_point`):
#: zero-sized at the origin, so it can never leak a real dimension.
_HAND_FRAME_BOX = Box(0.0, 0.0, 0.0, 0.0)


def round_half_away(value: float) -> int:
    """Round half away from zero: a mirrored ``dx: -1.5px``/``dx: 1.5px``
    pair must resolve to ``-2``/``2``, so a symmetric hand stays symmetric.
    Plain ``round()`` is sign-symmetric too, but rounds half to even
    (``0.5`` -> ``0``).  `wfb.preview` imports this for `WfbArc`'s degrees.
    """
    return int(value - 0.5) if value < 0 else int(value + 0.5)


def alignment_shift(width: float, height: float, align: str, vertical_align: str) -> tuple[float, float]:
    """How far a placement box's centre sits from the point ``at:`` resolves
    to: ``align``/``vertical_align`` say which edge (or the centre) of the
    box sits on that point, independently per axis.  ``center``/``center``
    adds exactly ``0.0``.  The one rule for every box-drawn kind, for a
    glyph kind's lint box, and -- in the part's own frame, before rounding --
    for a hand/pattern part.
    """
    dx = {"left": width / 2, "center": 0.0, "right": -width / 2}[align]
    dy = {"top": height / 2, "center": 0.0, "bottom": -height / 2}[vertical_align]
    return dx, dy


def garmin_arc(start: float, sweep: float) -> tuple[float, str]:
    """The author's arc angles in Garmin's ``drawArc`` convention.

    The format measures degrees clockwise from 12 o'clock; ``drawArc`` measures
    them counter-clockwise from 3 o'clock, so a positive (clockwise) sweep
    travels in the ``ARC_CLOCKWISE`` direction from ``90 - start``.  Shared by
    `shape: arc` and `progress: {style: arc}` so they cannot drift apart.
    """
    return (
        (90.0 - start) % 360.0,
        "ARC_CLOCKWISE" if sweep >= 0 else "ARC_COUNTER_CLOCKWISE",
    )


def garmin_curve_angle(style: str, angle: Angle) -> float:
    """`curve.angle` in `Dc.drawAngledText`/`Dc.drawRadialText`'s
    convention (degrees counter-clockwise from 3 o'clock).

    The two styles share the key but not the meaning.  **`radial`'s angle is
    a position** -- where on the circle the text is justified ("Angle to a
    point on the circle", the SDK doc) -- so it converts like every other
    direction in the format (`Angle.to_garmin`, 12 o'clock = 0).  **`angled`'s
    angle is a rotation** of the baseline from level ("Angle of the text
    baseline ... counter-clockwise from the 3 o'clock position"), so `0deg`
    is level text and only the sign flips.

    A radial pattern composes either with its per-copy rotation by plain
    subtraction (`_pattern_text_ink`, `wfb.emit.monkeyc.rotated.
    _emit_pattern_text_angle_expr`): `to_garmin`'s offset, where there is
    one, is folded in once by the local angle, never per copy.
    """
    if style == "radial":
        return angle.to_garmin()
    return (-angle.degrees) % 360.0


def radial_direction_sign(direction: str | None) -> float:
    """`1.0` for `counter_clockwise` (increasing Garmin angle as the run is
    walked), `-1.0` for the default `clockwise` -- shared by
    `radial_text_angle_span` (the lint band) and the preview's own
    glyph-by-glyph placement (`wfb.preview._draw_radial_vector_text`)."""
    return 1.0 if direction == "counter_clockwise" else -1.0


def radial_align_offset(align: str, total_advance: float) -> float:
    """How far into a `curve: {style: radial}` run's own pixel length the
    anchor angle sits: `0.0` for `left` (the run starts on it), half for
    `center`, the whole length for `right` (it ends on it).  Shared by
    `radial_text_angle_span` and the preview's own per-glyph placement."""
    return {"left": 0.0, "center": total_advance / 2.0, "right": total_advance}[align]


def radial_text_angle_span(
    curve_angle_garmin: float, direction: str | None, align: str,
    total_advance: float, radius: float, pad: float = 0.0,
) -> tuple[float, float]:
    """The Garmin-degree interval a `curve: {style: radial}` run sweeps,
    using `wfb.preview._draw_radial_vector_text`'s own per-glyph placement
    model evaluated at the run's two ends: the run covers `total_advance`
    pixels starting `align_offset` before the anchor (`left` starts on it,
    `right` ends on it), divided by `radius` into degrees, with the sign set
    by `direction` (counter-clockwise advances Garmin angle).  Returned as
    `(theta_a, theta_b)`, not ordered -- `arc_bbox` takes either order.

    `pad` (an `outline:` ring, plan 15 D9) extends *both* ends by that many
    pixels.  It is added after the unpadded `align_offset`, not by widening
    `total_advance`, which would grow only the far end under `align: left`.
    """
    direction_sign = radial_direction_sign(direction)
    align_offset = radial_align_offset(align, total_advance)
    theta_a = curve_angle_garmin - direction_sign * math.degrees((align_offset + pad) / radius)
    theta_b = curve_angle_garmin + direction_sign * math.degrees(
        (total_advance - align_offset + pad) / radius)
    return theta_a, theta_b


def radial_text_band(
    radius: float, line_height: float, vertical_align: str, direction: str | None,
    ascent: float, pad: float = 0.0,
) -> tuple[float, float]:
    """The radii `(r_inner, r_outer)` a `curve: {style: radial}` run's ink
    spans, `r_inner <= r_outer`.

    **Device model** (measured on the simulator, `fenix8solar47mm`;
    `docs/research/12-vector-fonts.md` §5.3): `drawRadialText` knows two
    vertical placements.  With `TEXT_JUSTIFY_VCENTER` the line box's centre
    sits on the circle; without it the *baseline* does, glyphs growing
    toward their own "up".  So:

    * `center` -- `VCENTER`: `radius -/+ line_height / 2`.
    * `bottom` -- no flag: `ascent` on the "up" side, the descent
      (`line_height - ascent`) on the other.
    * `top` -- no flag, drawn at `radius -/+ ascent`
      (`wfb.emit.monkeyc.shapes._radial_radius_expr`), so the whole
      `line_height` lies on the "down" side.

    "Up" is outward under `clockwise` and inward under `counter_clockwise`.
    `ascent` stands in for the device's `getFontAscent`
    (`wfb.fonts.fallback.ascent`).

    `pad` grows both radii at the very end: `up`/`down` are asymmetric under
    `bottom`, so folding it into `line_height` would widen one side only.
    A negative `r_inner` is fine -- `arc_bbox` clamps it.
    """
    if vertical_align == "center":
        half = line_height / 2.0
        return radius - half - pad, radius + half + pad
    up, down = (ascent, line_height - ascent) if vertical_align == "bottom" else (0.0, line_height)
    if direction != "counter_clockwise":  # clockwise (default): "up" is outward
        return radius - down - pad, radius + up + pad
    return radius - up - pad, radius + down + pad


def _curve_ascent(metric: FontMetric | None, line_height: float,
                  fonts_root: str | None = None) -> float:
    """`radial_text_band`'s `ascent` for a curved run's font -- always a
    vector font's synthesised metric in practice (`curve:` refuses any
    other kind); a missing one takes the whole line height. `fonts_root`
    is the device's own `--fonts DIR` override (`Device.fonts_root`), so
    this locates the same file `wfb.layout`/`wfb.preview` measure and draw
    the same run with (plan 18 item 8)."""
    return fallback.ascent(metric, fonts_root=fonts_root) if metric is not None else line_height


def arc_bbox(
    cx: float, cy: float, r_inner: float, r_outer: float,
    theta_a_degrees: float, theta_b_degrees: float,
) -> Box:
    """The axis-aligned bounding box of an annulus sector: radii
    `r_inner`..`r_outer` (`r_inner` clamped to `>= 0`, so a sector dipping
    past the centre becomes a pie slice rather than wrapping), swept between
    `theta_a_degrees` and `theta_b_degrees` (either order) -- Garmin degrees,
    counter-clockwise from 3 o'clock, screen y down (`px = cx + r*cos`,
    `py = cy - r*sin`).

    The four corner points alone are not enough: an arc crossing due north
    has its topmost point mid-sweep.  So each axis extreme (3, 12, 9 and 6
    o'clock) inside the sweep is added too, at the outer radius -- the inner
    radius is never the extreme there.
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


def rotated_rect_corners(
    x: float, y: float, width: float, height: float, align: str, vertical_align: str,
    garmin_angle_degrees: float, pad: float = 0.0,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
    """The four real corners of a `width`x`height` text box anchored at
    `(x, y)`, shifted by `align`/`vertical_align` in its own unrotated frame
    (`alignment_shift`), then rotated about `(x, y)` by
    `garmin_angle_degrees` -- the rotation `drawAngledText` applies
    (verified against `$CIQ_SDK/samples/TrueTypeFonts/.../
    TrueTypeFontsAngledText.mc`: Garmin angle 0 is unrotated).  `InkQuad`
    keeps the corners themselves, since the AABB's corners are not points
    of the rectangle and overreach it on a round screen.

    `pad` grows the half-extents in the box's local frame *without* moving
    its centre -- alignment still reads the unpadded size.  Conservative: at
    a corner this reaches up to `pad * sqrt(2)` past the true stamped ring
    (research 14 §3.2).
    """
    theta = math.radians(garmin_angle_degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    dx, dy = alignment_shift(width, height, align, vertical_align)
    cx = x + dx * cos_t + dy * sin_t
    cy = y - dx * sin_t + dy * cos_t
    hw, hh = width / 2.0 + pad, height / 2.0 + pad
    corners = []
    for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        corners.append((cx + lx * cos_t + ly * sin_t, cy - lx * sin_t + ly * cos_t))
    return corners[0], corners[1], corners[2], corners[3]


def annulus_sector_reach(
    cx: float, cy: float, r_inner: float, r_outer: float,
    theta_a_degrees: float, theta_b_degrees: float, px: float, py: float,
) -> float:
    """The farthest distance from `(px, py)` to any point of the annulus
    sector `arc_bbox` bounds (same arguments and convention) -- what the
    round-screen `safe-area` check needs, since the AABB's corners sit
    farther out than the sector ever does.

    A circle's farthest point from `P` lies straight away from `P` through
    the centre, at `dist + r_outer`; when that direction falls inside the
    sweep, that is the answer.  Otherwise the maximum is at one of the
    sweep's two ends (distance at a fixed angle is convex in the radius), so
    both radii at both ends suffice.  Exact for the sectors this project
    builds (one run of text, never a reflex sweep).
    """
    dist_c = math.hypot(cx - px, cy - py)
    theta_min = min(theta_a_degrees, theta_b_degrees)
    theta_max = max(theta_a_degrees, theta_b_degrees)
    sweep = theta_max - theta_min
    r_inner = max(0.0, r_inner)
    if sweep >= 360.0 or dist_c < 1e-9:
        return dist_c + r_outer
    theta_far = math.degrees(math.atan2(-(cy - py), cx - px)) % 360.0
    if (theta_far - theta_min) % 360.0 <= sweep:
        return dist_c + r_outer
    best = 0.0
    for theta in (theta_min, theta_max):
        rad = math.radians(theta)
        cos_t, sin_t = math.cos(rad), math.sin(rad)
        for r in (r_inner, r_outer):
            x, y = cx + r * cos_t, cy - r * sin_t
            best = max(best, math.hypot(x - px, y - py))
    return best


# -- ink shapes ------------------------------------------------------------
#
# The real ink of a drawn thing, as one of four small shapes.  Each answers
# the three questions the lints ask, from the one shape: `box()` (the AABB,
# for the rectangular framebuffer and `Placed.box`), `bounds()` (the same
# AABB as `(min_x, min_y, max_x, max_y)`, for unioning a pattern's copies)
# and `reach(px, py)` (the farthest ink from a point, for the round-screen
# `safe-area` check -- an AABB's own corners generically overreach the shape
# they bound).  `box()`/`bounds()` each keep the arithmetic their callers
# have always used, so neither is derived from the other.


@dataclass(frozen=True)
class InkRect:
    """A screen-aligned rectangle: upright text."""

    left: float
    top: float
    width: float
    height: float

    def box(self) -> Box:
        return Box(self.left, self.top, self.width, self.height)

    def bounds(self) -> tuple[float, float, float, float]:
        return self.left, self.top, self.left + self.width, self.top + self.height

    def reach(self, px: float, py: float) -> float:
        left, top, right, bottom = self.bounds()
        return max(math.hypot(x - px, y - py)
                   for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)))


@dataclass(frozen=True)
class InkQuad:
    """Four real corners (:func:`rotated_rect_corners`): `angled` text."""

    corners: tuple[tuple[float, float], ...]

    def box(self) -> Box:
        min_x, min_y, max_x, max_y = self.bounds()
        return Box(min_x, min_y, max_x - min_x, max_y - min_y)

    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.corners]
        ys = [p[1] for p in self.corners]
        return min(xs), min(ys), max(xs), max(ys)

    def reach(self, px: float, py: float) -> float:
        return max(math.hypot(x - px, y - py) for x, y in self.corners)


@dataclass(frozen=True)
class InkSector:
    """An annulus sector (:func:`arc_bbox`'s convention): `radial` text."""

    cx: float
    cy: float
    r_inner: float
    r_outer: float
    theta_a: float
    theta_b: float

    def box(self) -> Box:
        return arc_bbox(self.cx, self.cy, self.r_inner, self.r_outer, self.theta_a, self.theta_b)

    def bounds(self) -> tuple[float, float, float, float]:
        b = self.box()
        return b.x, b.y, b.x + b.width, b.y + b.height

    def reach(self, px: float, py: float) -> float:
        return annulus_sector_reach(self.cx, self.cy, self.r_inner, self.r_outer,
                                    self.theta_a, self.theta_b, px, py)


@dataclass(frozen=True)
class InkDisc:
    """A full disc: every `circular_extent` kind."""

    cx: float
    cy: float
    radius: float

    def box(self) -> Box:
        r = self.radius
        return Box(self.cx - r, self.cy - r, 2 * r, 2 * r)

    def bounds(self) -> tuple[float, float, float, float]:
        r = self.radius
        return self.cx - r, self.cy - r, self.cx + r, self.cy + r

    def reach(self, px: float, py: float) -> float:
        return math.hypot(self.cx - px, self.cy - py) + self.radius


Ink = InkRect | InkQuad | InkSector | InkDisc


def text_ink(
    x: float, y: float, width: float, height: float, align: str, vertical_align: str, *,
    curve_style: str | None, angle_garmin: float, radius_px: int, direction: str | None,
    metric: FontMetric | None, pad: float, fonts_root: str | None = None,
) -> Ink:
    """The ink of one measured `width`x`height` run anchored at `(x, y)` --
    the one derivation shared by a standalone `text` element
    (`wfb.kinds.text.resolve`'s box, `visible_reach`) and a pattern's
    `shape: text` part (`wfb.kinds.pattern._pattern_part_ink`,
    `wfb.kinds.pattern.resolve`'s reach), so box and reach always describe
    the same shape.

    * upright -- the box moved by `alignment_shift`; the runtime anchor
      stays put (a glyph kind aligns by device-side justify).
    * `angled` -- that box rotated about the anchor by `angle_garmin`
      (:func:`rotated_rect_corners`), conservative: the whole line box, not
      the glyphs' own ink.
    * `radial` -- `(x, y)` is the circle's centre; the sector swept by the
      run (:func:`radial_text_angle_span`) over the band
      (:func:`radial_text_band`).  A square around the circle would put its
      corners at `(radius + line_height) * sqrt(2)`, far outside a round
      panel the glyphs themselves never leave.  With no usable radius
      (schema-unreachable) a conservative disc instead.

    `pad` is an `outline:` ring's width (plan 15 D9): the box is dilated
    about its already-aligned centre, never re-anchored as a wider box --
    alignment still reads the unpadded `width`/`height`.

    `fonts_root` (the device's own `--fonts DIR` override, `Device.
    fonts_root`) only matters for `radial`'s own `_curve_ascent` -- the one
    call here that can re-locate a font file.
    """
    if curve_style == "angled":
        return InkQuad(rotated_rect_corners(
            x, y, width, height, align, vertical_align, angle_garmin, pad=pad))
    if curve_style == "radial":
        if radius_px <= 0:
            return InkDisc(x, y, radius_px + height + pad)
        theta_a, theta_b = radial_text_angle_span(
            angle_garmin, direction, align, width, radius_px, pad=pad)
        r_inner, r_outer = radial_text_band(
            radius_px, height, vertical_align, direction,
            _curve_ascent(metric, height, fonts_root), pad=pad)
        return InkSector(x, y, r_inner, r_outer, theta_a, theta_b)
    dx, dy = alignment_shift(width, height, align, vertical_align)
    box_width, box_height = width + 2 * pad, height + 2 * pad
    return InkRect(x + dx - box_width / 2, y + dy - box_height / 2, box_width, box_height)


def _stroke_pad(pen: int) -> int:
    """How far a stroked outline's ink reaches past the declared edge it is
    drawn on: half the pen, plus a pixel for the device's rounding."""
    return pen // 2 + 1


def _arc_box(
    radius: int, pen: int, cx: float, cy: float, align: str, vertical_align: str,
    start_angle: Angle | None, sweep_angle: Angle | None,
) -> tuple[IntBox, float, float, float, float, float, str]:
    """What `shape: arc` and `progress: {style: arc}` share once `radius`
    and `pen` are resolved: the alignment shift by the full circle
    (`start_angle:`/`sweep:` never move the centre), the stroked reach and
    `garmin_arc`.  The callers resolve `radius`/`pen` themselves because
    they do so in opposite orders, and that order is `Resolver.sub_pixel`'s.

    Returns ``(box, cx, cy, start_degrees, sweep_degrees, garmin_start,
    garmin_direction)``, with the shifted centre.
    """
    dx, dy = alignment_shift(2 * radius, 2 * radius, align, vertical_align)
    cx, cy = cx + dx, cy + dy
    reach = radius + _stroke_pad(pen)
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
    #: The `aod: {thickness: ...}` override (`Resolver._aod_extent`), or
    #: `None` for none -- codegen then keeps the plain `_THICKNESS` constant.
    #: A rendering fact only: never affects `box`/`rect`.
    aod_thickness: int | None = None


@dataclass(frozen=True)
class ResolvedFont:
    """A text font resolved for one device -- the part of `Resolver._text_font`
    a placed text, a pattern's text part and a complication slot's reading
    carry into codegen, preview and lint."""

    #: The `Rez.Fonts` key of a baked font, the `FONT_*` symbol of a system
    #: font, or the declared name of a `face:` (vector) font.
    reference: str = ""
    is_custom: bool = False
    px: int = 0
    #: What the text is measured (and previewed) through: the device's
    #: metric for a system font, or one synthesised for a resolved vector
    #: face (`Resolver._vector_font_metric`).  `None` for a baked font, or
    #: when the device has no metrics for the system symbol.
    metric: FontMetric | None = None
    #: **Vector fonts only.**  The one face name this device publishes out
    #: of `FontSpec.face`'s candidates (`Resolver._resolve_vector_face`) --
    #: what codegen emits as `:face`; empty when none resolves.
    face: str = ""
    #: True when the font is a `face:` (vector) font.
    is_vector: bool = False
    #: Whether vector gates 1-3 passed on this device (always `True` for a
    #: baked or system font).  `False` survives into a build only under
    #: `if_unavailable: hide` (`wfb.lint.check_vector_font_availability`):
    #: the element still resolves, but nothing draws it on this device.
    available: bool = True


@dataclass(frozen=True)
class ResolvedCurve:
    """A text's `curve:` resolved for one device. `style` is `"angled"`,
    `"radial"`, or `None` for upright text (the default). The angle is kept
    in author units and in Garmin's convention (`garmin_curve_angle` -- a
    *position* for `radial`, a *rotation* for `angled`); `radius_px` is
    the resolved radius (`radial` only, else `0`); `direction` is the
    author's word."""

    style: str | None = None
    angle_degrees: float = 0.0
    angle_garmin: float = 0.0
    radius_px: int = 0
    direction: str | None = None


def resolved_curve(curve: Curve | None) -> ResolvedCurve:
    """`curve:`'s style, angles and direction; the caller resolves the
    radius in its own frame (`dataclasses.replace(..., radius_px=...)`)."""
    if curve is None:
        return ResolvedCurve()
    return ResolvedCurve(curve.style, curve.angle.degrees,
                         garmin_curve_angle(curve.style, curve.angle), 0, curve.direction)


@dataclass
class PlacedText(Placed):
    #: The point passed to ``drawText``; ``justify`` says how text sits on it.
    #: Under `curve: {style: radial}` it is the circle's centre instead.
    anchor_point: tuple[int, int] = (0, 0)
    justify: tuple[str, ...] = ()
    font: ResolvedFont = ResolvedFont()
    widest: str = ""
    measured_width: int = 0
    #: True when the extent was estimated rather than measured from real metrics.
    width_is_estimated: bool = False
    curve: ResolvedCurve = ResolvedCurve()
    #: The measured (or estimated) line height, in device pixels -- what
    #: `visible_reach` rebuilds a curved element's ink from (`text_ink`).
    line_height: float = 0.0


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
    #: See `PlacedShape.aod_thickness` -- `style: arc` only.
    aod_thickness: int | None = None


@dataclass
class PlacedIcon(Placed):
    #: The requested *visual* pixel size -- not the font's own nominal size it
    #: was baked at, which `wfb.icons.bake_size` may inflate to compensate for
    #: how much the icon font's icon sets pad a glyph inside its em-square.
    size: int = 0
    #: The synthetic font resource this icon draws from (see `wfb.icons.font_key`).
    font_key: str = ""
    #: For a static icon, the glyph itself.  For a dynamic icon
    #: (`element.is_dynamic`), the *representative* glyph measurement and
    #: preview use (`wfb.icons.WEATHER_BAKE_REFERENCE_GLYPH`); codegen picks
    #: the real one on-device.
    codepoint: str = "?"
    anchor_point: tuple[int, int] = (0, 0)
    #: `TEXT_JUSTIFY_*` flags: a glyph kind aligns by device-side justify on
    #: the unshifted anchor, not by a build-time box move.
    justify: tuple[str, ...] = ()


@dataclass
class PlacedGraph(Placed):
    """A `graph`, resolved: the drawn box, and the two style-specific widths.
    Everything series-dependent is device-independent and stays on the IR
    (`Graph.sample_count`, `series_def`)."""

    thickness: int = 1
    bar_width: int = 1
    size: tuple[int, int] = (0, 0)
    #: See `PlacedShape.aod_thickness` -- for a `line`/`bars` graph respectively.
    aod_thickness: int | None = None
    aod_bar_width: int | None = None


@dataclass(frozen=True)
class ResolvedHandPart:
    """One hand part, or one pattern template part, resolved for one
    device: whole pixels, in the part's own frame (origin = the axis / the
    pattern's `at:`, pointing at 12 o'clock) -- the shape the watch rotates
    (or translates) at runtime.  One class covers every runtime shape; a
    rectangle part is folded into ``polygon`` (a rotated rectangle is a
    polygon).  ``arc`` and ``text`` are pattern-only
    (`wfb.ir.HAND_PART_REJECTED_SHAPES`).
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
    #: ``circle``/``arc``/``text``: centre or anchor (``arc``'s is always the
    #: origin); ``circle``/``arc``: radius; ``line``/unfilled ``circle``/
    #: ``arc``: pen width.
    x: int = 0
    y: int = 0
    radius: int = 0
    thickness: int = 1
    filled: bool = True
    #: ``arc`` only.  Author degrees (12 o'clock = 0, clockwise), always set
    #: explicitly; a radial pattern adds ``start + i * step`` at runtime.
    start_angle: float = 0.0
    sweep: float = 0.0
    #: ``text`` only, from here down -- the same meaning as the matching
    #: `PlacedText` fields.
    font: ResolvedFont = ResolvedFont()
    justify: tuple[str, ...] = ()
    align: str = "center"
    vertical_align: str = "center"
    line_height: int = 0
    #: The host-rendered string for every copy index ``0..count-1`` (skipped
    #: copies included, so ``texts[i]`` is copy ``i``), and each one's
    #: measured pixel width, in the same order.
    texts: tuple[str, ...] = ()
    widths: tuple[int, ...] = ()
    #: `curve.angle_garmin` is the part's *local* angle, for copy 0 only: a
    #: radial pattern's per-copy rotation depends on the runtime copy index,
    #: so it is composed where that index is known (`wfb.kinds.pattern.
    #: _pattern_text_ink`, `wfb.kinds.pattern._emit_pattern_text_angle_expr`).
    curve: ResolvedCurve = ResolvedCurve()
    #: `HandPart.outline`, exploded; `outline_color is None` means none.
    outline_width: int = 0
    outline_color: Expression | None = None


@dataclass(frozen=True)
class ResolvedHand:
    parts: tuple[ResolvedHandPart, ...] = ()


@dataclass
class PlacedHands(Placed):
    """A `type: hands` element, resolved: the axis (``center``), each
    declared hand's resolved parts, and the swept disc (``box`` is the
    square around it).
    """

    hour: ResolvedHand | None = None
    minute: ResolvedHand | None = None
    second: ResolvedHand | None = None
    #: The farthest ink of any part of any drawn hand from the axis --
    #: `circular_extent` reads this instead of `box`, so the visible-area
    #: check reasons about the real disc, not its bounding square.
    reach: float = 0.0
    #: The `aod: {thickness: ...}` override, one value for every part of
    #: every hand (plan 14 §5.1); `None` for none.
    aod_thickness: int | None = None


@dataclass
class PlacedPattern(Placed):
    """A `type: pattern` element, resolved: the template, which copies are
    drawn, and the repeat rule -- radial (turn about ``center``) or linear
    (step by `dx`/`dy` from copy 0 at ``center``).  ``box`` bounds the ink
    of every *drawn* copy.
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
    #: Radial only: the farthest ink of any part of any drawn copy from
    #: `center` (`circular_extent` reads it, like `PlacedHands.reach`); `0`
    #: for a linear pattern, which reports no disc.
    reach: float = 0.0
    #: See `PlacedHands.aod_thickness`.
    aod_thickness: int | None = None

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


def is_antialiased_primitive(placed: "Placed") -> bool:
    """Does this placed element's own drawing `antialias:` reach as a
    runtime `Dc.setAntiAlias` -- true for a primitive-drawing kind
    (`shape`/`progress`/`graph`/`hands`/`pattern`), never for a glyph kind
    (`text`/`icon`/`complication_slot`, which anti-alias in their baked
    font instead) or a `group`.  Read by the emitter's "is the feature used"
    gate, its per-element toggle, and the `antialias-dither` lint: three
    private copies once drifted, so a hands-only anti-aliased face emitted
    no `setAntiAlias` at all, and a graph-only one never linted."""
    return kinds.for_placed(placed).antialiased


#: The pixel gap between a complication_slot's icon and its reading when
#: `icon_gap:` is not authored -- a fixed literal the generated view inlines.
COMPLICATION_SLOT_ICON_GAP = 4


@dataclass(frozen=True)
class SlotPairGeometry:
    """The icon+reading pair's combined extent, and each piece's offset from
    the pair's own top-left corner -- shared by
    `wfb.kinds.complication_slot.resolve` (the estimated lint box) and
    `wfb.preview` (the drawn pixels).  The generated Monkey C mirrors the
    arithmetic rather than receiving these numbers: the real text is only
    known once the value is pulled at runtime (ADR 0004's one exception).
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
    lints, plus what the emitter needs to draw the icon and reading.

    `box`/`widest` are an *estimate*: the drawn extent depends on the
    wearer's pick and its current value, neither known at build time.  The
    device centres the real pair on `anchor_point` itself, so this box is
    for the safe-area/off-screen checks only.
    """

    anchor_point: tuple[int, int] = (0, 0)
    #: The slot's own reading text; never a vector font (the builder
    #: rejects one).
    font: ResolvedFont = ResolvedFont()
    #: The widest plausible reading
    #: (`wfb.kinds.complication_slot._complication_slot_widest`).
    widest: str = ""
    #: The synthetic multi-glyph icon font (`wfb.icons.font_key`), or `None`
    #: when the slot draws no icon (no `icon_size:`, or no choice has one).
    icon_font_key: str | None = None
    icon_px: int = 0
    icon_position: str = "left"
    #: `icon_gap:` resolved for this device, else `COMPLICATION_SLOT_ICON_GAP`.
    icon_gap_px: int = COMPLICATION_SLOT_ICON_GAP


@dataclass(frozen=True)
class _Owner:
    """Who a `SubPixelLength` is recorded against (`Resolver._owned_by`)."""

    id: str
    span: Span | None
    element: Element


@dataclass(frozen=True)
class SubPixelLength:
    """A nonzero %/%r extent that resolved below 1 px on this device with
    `min_1px` off -- it rounds away to nothing here while drawing on a
    larger screen.  Recorded by `Resolver._extent`, read by
    `wfb.lint.check_sub_pixel_length`.
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
    #: Every `SubPixelLength` this device's resolve recorded, in resolve
    #: order, not deduplicated -- the lint decides how to present them.
    sub_pixel: list[SubPixelLength] = field(default_factory=list)

    def in_mode(self, mode: str) -> list[Placed]:
        return [p for p in self.items if mode in p.element.modes]

    def drawn_in_mode(self, mode: str) -> list[Placed]:
        """``in_mode`` minus groups -- everything that actually paints in ``mode``.

        A group paints nothing of its own, and one with no ``size:`` resolves
        to its whole parent box, so its box is no evidence of drawing.  A
        clip rectangle or an element count wants this, not ``in_mode``.
        """
        return [p for p in self.in_mode(mode) if p.kind != "group"]

    def clip_for(self, mode: str) -> IntBox | None:
        """The tightest rectangle covering everything drawn in ``mode``.

        ``setClip`` is charged by *region area*, so this being tight is what
        keeps ``onPartialUpdate`` inside its budget.  Built from
        :meth:`drawn_in_mode`, so a group's box never inflates it.

        Unions across every layout: `_configLayout` is a runtime value, and
        the emitter sets one clip before its per-layout guards.  A clip per
        layout would need setting inside each guard -- a possible
        optimisation, not built.
        """
        boxes = [p.box for p in self.drawn_in_mode(mode)]
        if not boxes:
            return None
        clip = boxes[0]
        for box in boxes[1:]:
            clip = clip.union(box)
        return clip.inflate(1).clamp_to(self.device.width, self.device.height)


@dataclass(frozen=True)
class _Font:
    """One text font, resolved for this device: what `_font_for_ref` finds,
    plus -- for a `face:` font -- gates 1-3's answer (`Resolver._text_font`).
    `baked` is the baked sheet (never a vector font's); `metric` the
    `FontMetric` a system or vector font is measured through. `fonts_root`
    is the device's own `--fonts DIR` override (`Device.fonts_root`), so a
    system/vector font is measured with the same file `wfb.preview` then
    draws with (plan 18 item 8)."""

    px: int
    reference: str
    is_custom: bool
    baked: BakedFont | None
    metric: FontMetric | None
    face: str = ""
    is_vector: bool = False
    available: bool = True
    fonts_root: str | None = None

    def width(self, text: str) -> int:
        """`text`'s advance: exact for a baked sheet; for a system or vector
        font an estimate from the device's own typeface (or a stand-in) at
        the device's published metrics; `0` with no metrics at all."""
        if self.baked is not None:
            return self.baked.measure(text)[0]
        return fallback.measure(text, self.metric, fonts_root=self.fonts_root)[0] if self.metric else 0

    @property
    def line_height(self) -> int:
        if self.baked is not None:
            return self.baked.line_height
        return (fallback.line_height(self.metric, fonts_root=self.fonts_root)
                if self.metric else self.px)

    def resolved(self) -> ResolvedFont:
        """What a placed element carries of this font."""
        return ResolvedFont(self.reference, self.is_custom, self.px, self.metric,
                            self.face, self.is_vector, self.available)


class Resolver:
    def __init__(self, face: Face, device: Device, fonts: dict[str, BakedFont]) -> None:
        self.face = face
        self.device = device
        self.fonts = fonts
        self.screen = Box(0, 0, device.width, device.height)
        self.minor_radius = device.minor_radius
        self.items: list[Placed] = []
        self.warnings: list[str] = []
        #: `SubPixelLength`s, in resolve order (`_extent`, `_record_sub_pixel`).
        self.sub_pixel: list[SubPixelLength] = []
        #: Who a `SubPixelLength` is recorded against (`_owned_by`): the
        #: element being resolved (`_resolve_list`), narrowed to a part's own
        #: id/span while `_resolve_hand_part` runs -- the element stays the
        #: owner, since a part has no `lint:` key of its own to suppress
        #: against. Each scope restores the previous owner when it ends.
        self._owner: _Owner | None = None

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
            with self._owned_by(_Owner(element.id, element.span, element)):
                if isinstance(element, Group):
                    box = self._group_box(element, parent)
                    self.items.append(
                        Placed(element, box.rounded(min_1px=element.resolved_min_1px),
                               (round(box.center_x), round(box.center_y)), depth)
                    )
                    self._resolve_list(element.items, box, depth + 1)
                else:
                    resolve = kinds.for_element(element).resolve
                    self.items.append(resolve(self, element, parent, depth))

    @contextmanager
    def _owned_by(self, owner: "_Owner"):
        """Record every `SubPixelLength` inside this scope against `owner`,
        then restore whoever owned them before."""
        previous, self._owner = self._owner, owner
        try:
            yield
        finally:
            self._owner = previous

    # -- per-kind ---------------------------------------------------------

    def _sized_box(
        self, element: Group | Shape | Progress | Graph, parent: Box, cx: float, cy: float,
    ) -> tuple[Box, float, float]:
        """The "size, then align" box every `size:`-placed kind shares, and
        its shifted centre.  Width then height go through `_extent` in that
        order -- `sub_pixel`'s order.  Takes the anchor already resolved,
        since `wfb.kinds.shape.resolve` needs it first (`_point` records nothing).
        """
        min_1px = element.resolved_min_1px
        width = self._extent(element.size.width, parent, Axis.X, parent.width,
                             min_1px=min_1px, what="size.width")
        height = self._extent(element.size.height, parent, Axis.Y, parent.height,
                              min_1px=min_1px, what="size.height")
        dx, dy = alignment_shift(width, height, element.align, element.vertical_align)
        cx, cy = cx + dx, cy + dy
        return Box(cx - width / 2, cy - height / 2, width, height), cx, cy

    def _group_box(self, element: Group, parent: Box) -> Box:
        cx, cy = self._point(element.at, parent)
        return self._sized_box(element, parent, cx, cy)[0]

    def _text_font(self, font: str, font_is_custom: bool, warn_id: str,
                   curve: Curve | None) -> _Font:
        """`_font_for_ref`, plus gates 1-3 for a `face:` (vector) font: its
        baked sheet and system metric are both meaningless (nothing bakes a
        vector font), so they give way to this device's resolved face and a
        metric synthesised for it.  Shared by a `text` element and a
        pattern's `shape: text` part."""
        resolved = self._font_for_ref(font, font_is_custom, warn_id)
        if not resolved.is_custom:
            return resolved
        spec = self.face.fonts[font]
        if not spec.is_vector:
            return resolved
        face, available = self._resolve_vector_face(spec, curve)
        return replace(resolved, baked=None, metric=self._vector_font_metric(face, resolved.px),
                       face=face, is_vector=True, available=available)

    def _vector_gate1_ok(self, curve_style: str | None) -> bool:
        """Gate 1 (`docs/research/12-vector-fonts.md` §3): does this device
        have `Graphics.getVectorFont` -- and, under `curve:`, the matching
        `Dc.drawAngledText`/`Dc.drawRadialText`?  Checked separately: they
        move together on every installed device, but nothing in the SDK
        promises that across the fleet.
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
        """Gates 1-3 (plan 11 §1) for one `face:` `FontSpec`, on this device:
        the *first* of `spec.face`'s candidates this device publishes
        (`Device.scalable_faces`) and `True`, or `("", False)`.  One name,
        never the array: a runtime pick could not be measured or named in an
        error.  `wfb.lint.check_vector_font_availability` turns a failure
        into an error or warning once every target is resolved.
        """
        if not self._vector_gate1_ok(curve.style if curve is not None else None):
            return "", False
        for name in spec.face:
            if name in self.device.scalable_faces:
                return name, True
        return "", False

    def _vector_font_metric(self, face_name: str, font_px: int) -> FontMetric:
        """A synthetic `FontMetric` for a vector face, so `wfb.fonts.fallback`
        measures it exactly like a system font.  `font` is the on-disk stem
        (`Device.scalable_face_files`: `"RobotoCondensed-Bold"`, not the
        `:face` string `"RobotoCondensedBold"`), which is what the font
        locators match.  An empty `face_name` locates nothing and falls to
        Pillow's default at `font_px` -- conservative, never zero.  A vector
        font has no separate published line height, so `size_px` is its
        `:size` in pixels.
        """
        filename = self.device.scalable_face_files.get(face_name, face_name)
        return FontMetric(symbol=face_name or "vector", face=face_name, font=filename,
                          size_px=font_px)

    def _resolve_parts(
        self, parts: list[HandPart], owner: str, *, min_1px: bool,
    ) -> tuple[tuple[ResolvedHandPart, ...], float]:
        """Every part of one `parts:` list (a hand's, or a pattern's
        template), plus the farthest reach among them.  `owner` prefixes
        each part's own id, `<owner>.parts[<i>]`."""
        resolved = []
        reach = 0.0
        for index, part in enumerate(parts):
            resolved_part, part_reach = self._resolve_hand_part(part, owner, index, min_1px=min_1px)
            resolved.append(resolved_part)
            reach = max(reach, part_reach)
        return tuple(resolved), reach

    def _resolve_hand_part(
        self, part: HandPart, owner: str, index: int, *, min_1px: bool,
    ) -> tuple[ResolvedHandPart, float]:
        """:meth:`_hand_part_geometry`, with the part (`<owner>.parts[<index>]`,
        its own span) as the owner of any `SubPixelLength` it raises, for
        the part's duration only."""
        owner_id = f"{owner}.parts[{index}]"
        assert self._owner is not None, "no element is being resolved yet"
        with self._owned_by(replace(self._owner, id=owner_id, span=part.span)):
            return self._hand_part_geometry(part, owner_id, min_1px=min_1px)

    def _hand_part_geometry(
        self, part: HandPart, owner_id: str, *, min_1px: bool,
    ) -> tuple[ResolvedHandPart, float]:
        """One hand or pattern part -> whole-pixel geometry in its own frame
        (origin = the axis / the pattern's `at:`, 12 o'clock up), plus its
        reach from that origin (the farthest ink it touches).  Rounds with
        :func:`round_half_away`, so a mirrored `dx: -1.5px`/`1.5px` pair
        stays symmetric.

        `owner_id` (`<owner>.parts[<index>]`) names the part in any "no
        pixel metrics" warning it raises. `min_1px` is the owning element's
        resolved value; the part's own `min_1px:` overrides it here, per
        placement, because one `hands:` set can be placed by several
        elements that resolve it differently.
        """
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
            # `wfb.kinds.shape.resolve` already uses in the parent's frame.
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
            # A pattern's template only.  Upright glyphs are not
            # rotation-invariant, so reach is `0.0` here:
            # `wfb.kinds.pattern.resolve` measures each drawn copy's own ink
            # instead.
            x0, y0 = self._hand_point(part.at)
            font = self._text_font(part.font, part.font_is_custom, owner_id, part.curve)
            curve = resolved_curve(part.curve)
            if curve.style == "radial" and part.curve.radius is not None:
                # Through `_hand_extent`, like any other part radius: a
                # relative one gets the `min_1px`/sub-pixel-length treatment.
                curve = replace(curve, radius_px=round_half_away(self._hand_extent(
                    part.curve.radius, min_1px=effective_min_1px, what="curve.radius")))
            outline = part.outline
            return ResolvedHandPart(
                "text", part.color, x=round_half_away(x0), y=round_half_away(y0),
                font=font.resolved(),
                justify=self._justify(part), align=part.align,
                vertical_align=part.vertical_align, line_height=font.line_height,
                texts=part.texts, widths=tuple(font.width(t) for t in part.texts),
                curve=curve,
                outline_width=outline.width if outline is not None else 0,
                outline_color=outline.color if outline is not None else None,
            ), 0.0

        # circle
        cx, cy = self._hand_point(part.at)
        radius = round_half_away(self._hand_extent(
            part.radius, min_1px=effective_min_1px, what="radius"))
        # The placement box is the full `2*radius` square,
        # at the resolved (already-rounded) radius the part draws with --
        # shifted before `reach`/`round_half_away` below, same as
        # `wfb.kinds.shape.resolve`'s circle branch in the parent's frame.
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

    # A hand/pattern part's own frame is `_point`/`_extent` over
    # `_HAND_FRAME_BOX`: every anchor of a zero box is the origin, and the
    # px/%r lengths a part may use (schema-enforced) never read the box.

    def _hand_point(self, at: Position) -> tuple[float, float]:
        return self._point(at, _HAND_FRAME_BOX)

    def _hand_extent(self, length: Length | None, default: float = 0, *,
                     min_1px: bool, what: str) -> float:
        return self._extent(length, _HAND_FRAME_BOX, Axis.MINOR, default,
                            min_1px=min_1px, what=what)

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
        """:meth:`_len`, then :func:`units.at_least_one_px` -- for a *size,
        thickness or radius*, never a position (`at:`/`to:`/points/`step:`
        stay on `_len`).  `min_1px` and `what` (the authored key, for the
        record) are required so no call site can silently default either.

        With `min_1px` off, a nonzero `%`/`%r` length under 1 px
        (:func:`units.is_sub_pixel_length`) is recorded as a
        `SubPixelLength` against the current owner -- the one place the
        `sub-pixel-length` lint's condition is visible.
        """
        value = self._len(length, parent, axis, default, font_px)
        if not min_1px and units.is_sub_pixel_length(length, value):
            self._record_sub_pixel(what, length, value)
        return units.at_least_one_px(length, value, min_1px)

    def _aod_extent(self, element: Element, key: str, parent: Box, default: float) -> int | None:
        """The `aod:` override of `key` (`thickness`/`bar_width`), resolved
        like the element's own (`_extent`, `Axis.MINOR`), or `None` when the
        resolved `aod:` does not override it -- codegen then keeps the plain
        constant (plan 14 §4.2).  Always `min_1px`, and never recorded as a
        `SubPixelLength`: an override is a restyling choice with no authored
        line of geometry for the lint to point at.  Never feeds `box`.
        """
        aod_length = getattr(element.aod, key) if element.aod is not None else None
        if aod_length is None:
            return None
        return max(1, round(self._extent(aod_length, parent, Axis.MINOR, default,
                                         min_1px=True, what="aod")))

    def _record_sub_pixel(self, key: str, length: Length | None, value: float) -> None:
        """Append one `SubPixelLength` for the current owner (`_extent`)."""
        assert length is not None
        assert self._owner is not None, "no element is being resolved yet"
        self.sub_pixel.append(SubPixelLength(
            owner=self._owner.id, key=key, length=length, value=value,
            span=self._owner.span, element=self._owner.element,
        ))

    def _font_for_ref(self, font: str, font_is_custom: bool, warn_id: str) -> _Font:
        """A `font:` reference resolved for this device, before any vector
        face gate (`_text_font` adds those): a custom font's baked sheet
        (or, unbaked -- a layout-only caller -- its declared size), or a
        system font's `FontMetric`, warning once when the device has none.
        The metric rides onto the `Placed*` so `wfb.preview` measures and
        draws through the same face (plan 09 §4 R2.3)."""
        if font_is_custom:
            baked = self.fonts.get(font)
            size = baked.size if baked else self.face.fonts[font].pixel_size(self.minor_radius)
            return _Font(size, font, True, baked, None, fonts_root=self.device.fonts_root)
        metric = self.device.system_fonts.get(font)
        if metric is None:
            self.warnings.append(
                f"{warn_id}: no pixel metrics for {font} on {self.device.id}; "
                f"text extent is not checked"
            )
        return _Font(metric.size_px if metric else 0, font, False, None, metric,
                     fonts_root=self.device.fonts_root)

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
    wins," the one rule `wfb.kinds.text._widest_text` (placeholder, fallback)
    and `wfb.kinds.complication_slot._complication_slot_widest` (per-choice
    estimate, placeholder) each repeated as their own
    ``if len(x) > len(y): y = x``.
    """
    return candidate if len(candidate) > len(current) else current


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
    return kinds.for_placed(placed).circular_extent(placed)


def _shape_ink(placed: "Placed", fonts_root: str | None = None) -> Ink | None:
    """The real ink shape where it is tighter than `placed.box`: a
    `circular_extent` kind's disc, or a curved `text` element's rotated box
    or sector -- rebuilt by :func:`text_ink` from the fields
    `wfb.kinds.text.resolve` stored, so it is the shape its box came from.
    `None` for everything else, whose box corners are its real corners.
    `fonts_root` (the device's own `--fonts DIR` override): see
    :func:`text_ink` -- this re-derivation must locate the same file
    `wfb.kinds.text.resolve` already measured with, or a `safe-area`
    check could disagree with the box it is re-checking (plan 18 item 8).
    """
    circle = circular_extent(placed)
    if circle is not None:
        return InkDisc(*circle)
    return kinds.for_placed(placed).ink(placed, fonts_root)


def visible_reach(placed: "Placed", screen_cx: float, screen_cy: float,
                  fonts_root: str | None = None) -> float | None:
    """The farthest distance any of `placed`'s own real ink can reach from
    `(screen_cx, screen_cy)` -- the round-screen `safe-area` check's
    shape-aware replacement for `placed.box`'s corners (`_shape_ink`).
    `None` means the box already is the shape: the caller falls back to
    the AABB-corners test (`inside_visible_area`), which also stays the
    right test for the rectangular framebuffer (`off-screen`).
    `fonts_root`: see :func:`_shape_ink`.
    """
    ink = _shape_ink(placed, fonts_root)
    return None if ink is None else ink.reach(screen_cx, screen_cy)


def inside_visible_area_for(placed: "Placed", device: Device) -> bool | None:
    """Visibility test that respects the element's actual shape."""
    if device.shape != "round":
        return inside_visible_area(placed.box, device)
    screen_cx, screen_cy = device.width / 2, device.height / 2
    reach = visible_reach(placed, screen_cx, screen_cy, device.fonts_root)
    if reach is None:
        return inside_visible_area(placed.box, device)
    limit = device.minor_radius * (1.0 - BEZEL_MARGIN)
    return reach <= limit + 0.5


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
    "inside_visible_area_for", "circular_extent", "is_antialiased_primitive",
    "visible_reach", "garmin_arc",
    "garmin_curve_angle", "alignment_shift", "round_half_away",
    "is_full_bleed", "arc_bbox", "annulus_sector_reach", "rotated_rect_corners",
    "radial_text_band", "radial_text_angle_span",
    "radial_direction_sign", "radial_align_offset",
]
