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
from .devices import Device
from .fonts import BakedFont, fallback
from .catalog import Type
from .ir import (
    ComplicationSlot, Element, Expression, Face, FontSpec, Graph, Group,
    HandPart, HandsElement, IconElement, PatternElement, Position, Progress, Shape, Size,
    Text, draw_sort_key,
)
from .units import ANCHORS, Angle, Axis, Box, IntBox, Length


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


def _round_away(value: float) -> int:
    """Round half away from zero -- plan 04 §5.3: a mirrored ``dx: -1.5px``/
    ``dx: 1.5px`` pair must resolve to ``-2``/``2``, so a symmetric hand
    stays symmetric on the panel.

    Plain ``round()`` (round half *to even*) happens to be sign-symmetric
    too, but lands on a different integer for some ``.5`` cases (``0.5``
    rounds to ``0``, not ``1``) -- the same distinction `wfb.preview`'s own
    `_round_away` (for `WfbArc`'s degrees) already draws, duplicated here
    rather than imported, because `wfb.layout` is resolved before any
    preview or codegen module and must not depend on either.
    """
    return int(value - 0.5) if value < 0 else int(value + 0.5)


def alignment_shift(width: float, height: float, align: str, vertical_align: str) -> tuple[float, float]:
    """How far a placement box's centre sits from the point ``at:`` resolves
    to (plan 07 §3.2(a)), for a box-drawn kind: ``align``/``vertical_align``
    say which edge (or the centre) of the box sits on that point,
    independently per axis. ``center``/``center`` -- the default, and the
    only value every pre-plan-07 design used -- adds exactly ``0.0`` on both
    axes, so a caller's default path is byte-identical to before this
    existed (R5).

    The one implementation of the rule for every box-drawn kind (R8):
    :meth:`Resolver._group_box`, :meth:`Resolver._resolve_text`'s lint box
    and :func:`_pattern_part_ink`'s text branch all call this instead of
    keeping their own ``left``/``center``/``right`` dict literal. Later
    phases (shape, progress, graph, icon, complication_slot, hand/pattern
    rectangle and circle parts) call it too, rather than write a sixth copy.
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
    anchor_point: tuple[int, int] = (0, 0)
    justify: tuple[str, ...] = ()
    font_reference: str = "FONT_MEDIUM"
    font_is_custom: bool = False
    font_px: int = 0
    widest: str = ""
    measured_width: int = 0
    #: True when the extent was estimated rather than measured from real metrics.
    width_is_estimated: bool = False


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
    #: how much the vendored font's icon sets pad a glyph inside its em-square.
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
    """One hand part, or one pattern template part (plan 05), resolved for
    one device: whole pixels, in the shared frame (origin = the axis /
    the pattern's own ``at:``, pointing at 12 o'clock) -- the shape the
    watch rotates (or translates) at runtime (plan 04 §5.3).  One class
    covers every runtime shape (``polygon``, ``line``, ``circle``, ``arc``)
    the same way :class:`PlacedShape` covers every ``shape:``; a rectangle
    part is folded into ``polygon`` here (`Resolver._resolve_hand_part`),
    because a rotated rectangle is a polygon (§5.2).  A hand never produces
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
    #: pattern's runtime rotation adds ``start + i * step`` to ``start_angle``
    #: (plan 05 §5.3); a linear one leaves it as authored.  The `0.0` default
    #: is never actually relied on: `Resolver._resolve_hand_part` always sets
    #: both explicitly for a real ``arc`` part (`sweep` defaulting to `360deg`
    #: there, not here, when the author omitted it).
    start_angle: float = 0.0
    sweep: float = 0.0
    #: ``text`` only (plan 06 §3.4) -- ``x``/``y`` double as the part's own
    #: anchor in the template frame (rounded via `_round_away`, the same as
    #: a circle's centre), everything else stays at its default on every
    #: other shape.  Upright glyphs are *not* rotation-invariant, so unlike
    #: every other shape a text part's own ``reach`` (`Resolver.
    #: _resolve_hand_part`'s return) is always `0.0`: the real farthest-ink
    #: distance is folded into `Resolver._resolve_pattern`'s per-copy loop
    #: instead, where each drawn copy's own upright box is known.
    font_reference: str = ""
    font_is_custom: bool = False
    font_px: int = 0
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


@dataclass(frozen=True)
class ResolvedHand:
    parts: tuple[ResolvedHandPart, ...] = ()


@dataclass
class PlacedHands(Placed):
    """A `type: hands` element, resolved: the axis, each declared hand's
    resolved parts, and the swept disc's reach (plan 04 §5.8).

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
    `center`) or linear (step by `dx`/`dy`) (plan 05 §6.2).

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
        the extent computation share (plan 05 §6.2) -- apply it to a
        template point ``(x, y)`` as ``ox + x*cos - y*sin, oy + x*sin +
        y*cos`` (§5.3's rotation, which collapses to a plain translation when
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
    part (plan 06 §3.2 D5): the template-frame point ``(part.x, part.y)``
    put through this copy's :meth:`PlacedPattern.transform`, then rounded
    **half up** (``floor(v + 0.5)``, not `_round_away`'s half-*away-from-
    zero* -- a hand-frame mirror-symmetry rule that does not apply here) --
    the device does the same ``(v + 0.5).toNumber()`` (`runtime-lib/
    WfbGeom.mc`), so the preview pixel and the device pixel agree.  A
    module-level function, not a method, so codegen and the preview
    (`docs/plans/06-pattern-text-and-group-align.md` phases B2/B3) can share
    it without importing a `Resolver`.
    """
    tx = ox + part.x * cos_t - part.y * sin_t
    ty = oy + part.x * sin_t + part.y * cos_t
    return math.floor(tx + 0.5), math.floor(ty + 0.5)


def _pattern_part_ink(
    part: ResolvedHandPart, ox: float, oy: float, sin_t: float, cos_t: float, index: int,
) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of one resolved pattern part's ink
    for one copy, given that copy's :meth:`PlacedPattern.transform` (plan 05
    §5.5): polygon vertices; a line's ends padded by half its pen width; a
    circle's centre padded by its radius (plus half the pen width when
    outlined); an arc's full circle -- always centred on the copy's own
    origin -- padded by half its pen width, conservatively ignoring
    `start_angle`/`sweep`; a text part's box, from its rounded anchor
    (:func:`pattern_text_anchor`) and this copy's own measured width
    (``part.widths[index]``, plan 06 §3.4) -- the one shape here that needs
    to know *which* copy it is, since upright text is not rotation-invariant.
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
        dx, dy = alignment_shift(width, height, part.align, part.vertical_align)
        left = ax + dx - width / 2.0
        top = ay + dy - height / 2.0
        return left, top, left + width, top + height
    # arc: always centred on the copy's own origin (plan 05 D3).
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
#: a design that never authors `icon_gap:` (plan 03 §6.1/§6.3): the literal
#: `4` a generated view embeds today, kept byte-identical rather than
#: promoted to a per-device constant when nothing asked for one.
COMPLICATION_SLOT_ICON_GAP = 4


@dataclass(frozen=True)
class SlotPairGeometry:
    """The icon+reading pair's combined extent, and each piece's offset from
    the pair's own top-left corner (plan 03 §6.3) -- shared by
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
    `bottom`) -- plan 03 §6.3, the one place this geometry is computed in
    Python.

    `icon_w`/`icon_h` are `(0, 0)` when the slot draws no icon at all (no
    declared choice resolves one, or the wearer's live pick does not on the
    device side) -- the gap then drops too and the text centres alone in
    every position, matching today's `left`-only behaviour.
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


@dataclass
class ResolvedFace:
    face: Face
    device: Device
    #: Flattened, in draw order (document order, then any explicit ``z``).
    items: list[Placed]
    fonts: dict[str, BakedFont]
    screen: IntBox
    warnings: list[str] = field(default_factory=list)

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

        **Unions across every layout, not just the active one** (plan 02
        §5.3, §5.6).  `_configLayout` is a runtime value
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
            screen=IntBox(0, 0, self.device.width, self.device.height),
            warnings=self.warnings,
        )

    # -- traversal --------------------------------------------------------

    def _resolve_list(self, elements: list[Element], parent: Box, depth: int) -> None:
        for element in elements:
            if isinstance(element, Group):
                box = self._group_box(element, parent)
                self.items.append(
                    Placed(element, box.rounded(),
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

    def _group_box(self, element: Group, parent: Box) -> Box:
        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        cx, cy = self._point(element.at, parent)
        dx, dy = alignment_shift(width, height, element.align, element.vertical_align)
        return Box(cx + dx - width / 2, cy + dy - height / 2, width, height)

    def _resolve_shape(self, element: Shape, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        thickness = round(self._len(element.thickness, parent, Axis.MINOR, 1))

        if element.shape == "circle":
            radius = round(self._len(element.radius, parent, Axis.MINOR, 0))
            reach = radius if element.filled else radius + max(1, thickness) // 2 + 1
            box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                               radius=radius, thickness=max(1, thickness))

        if element.shape == "line":
            ex, ey = self._point(element.to or Position(), parent)
            pad = max(1, thickness)
            box = Box(min(cx, ex) - pad, min(cy, ey) - pad,
                      abs(ex - cx) + 2 * pad, abs(ey - cy) + 2 * pad)
            return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                               thickness=max(1, thickness), end=(round(ex), round(ey)))

        if element.shape == "arc":
            radius = round(self._len(element.radius, parent, Axis.MINOR, 0))
            pen = max(1, thickness)
            # The same reach a `progress` arc claims: the pen straddles the
            # radius, so the ink runs half a pen width past it either side.
            reach = radius + pen // 2 + 1
            box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            start = (element.start_angle or Angle(0.0)).degrees
            sweep = (element.sweep or Angle(360.0)).degrees
            garmin_start, direction = garmin_arc(start, sweep)
            return PlacedShape(
                element, box.rounded(), (round(cx), round(cy)), depth,
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

        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)

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
        rect = Box(cx - width / 2, cy - height / 2, width, height).rounded()
        if element.filled:
            return PlacedShape(element, rect, (round(cx), round(cy)), depth,
                               corner_radius=corner, thickness=max(1, thickness))
        # An unfilled rectangle is stroked *on* its edge, so the ink straddles
        # the declared rectangle the same way a circle's outline straddles its
        # radius.  Until `filled:` was honoured at all this shape was always
        # filled, so this branch is new -- see `PlacedShape.rect`.
        pad = max(1, thickness) // 2 + 1
        reach = Box(rect.x - pad, rect.y - pad,
                    rect.width + 2 * pad, rect.height + 2 * pad).rounded()
        return PlacedShape(element, reach, (round(cx), round(cy)), depth,
                           corner_radius=corner, thickness=max(1, thickness), rect=rect)

    def _resolve_text(self, element: Text, parent: Box, depth: int) -> Placed:
        font_px, reference, is_custom, baked = self._font_for(element)
        widest = self._widest_text(element)
        if baked is not None:
            width, line_height = baked.measure(widest)
            estimated = False
        else:
            # A system font: the device publishes its pixel height but not its
            # glyph advances, and the real typeface is not available anywhere.
            # Measure a stand-in scaled to that height instead of assuming a flat
            # width per character -- '88888' and 'WWWWW' are not the same width.
            # Still an estimate, and still labelled as one.
            width, _ = fallback.measure(widest, font_px)
            line_height = font_px
            estimated = True

        x, y = self._point(element.at, parent)
        justify = self._justify(element)
        # The lint box only -- the runtime `drawText` anchor stays `(x, y)`
        # unshifted (mechanism (b), plan 07 §3.2): a glyph kind's alignment
        # is a device-side justify, not a build-time box move. `bottom`
        # (renamed from `baseline`, R6) already put this box's top at
        # `y - line_height`, which is where the §1.2 bug's *box* was always
        # right; only the actual draw call and the preview disagreed with it
        # (fixed below / in `wfb.emit.monkeyc` / `wfb.preview`).
        dx, dy = alignment_shift(width, line_height, element.align, element.vertical_align)
        box = Box(x + dx - width / 2, y + dy - line_height / 2, width, line_height)
        return PlacedText(
            element, box.rounded(), (round(x), round(y)), depth,
            anchor_point=(round(x), round(y)),
            justify=justify,
            font_reference=reference,
            font_is_custom=is_custom,
            font_px=font_px,
            widest=widest,
            measured_width=round(width),
            width_is_estimated=estimated,
        )

    def _resolve_progress(self, element: Progress, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        if element.style == "arc":
            radius = round(self._len(element.radius, parent, Axis.MINOR, 0))
            thickness = max(1, round(self._len(element.thickness, parent, Axis.MINOR, 1)))
            reach = radius + thickness // 2 + 1
            box = Box(cx - reach, cy - reach, 2 * reach, 2 * reach)
            start = (element.start_angle or Angle(0.0)).degrees
            sweep = (element.sweep or Angle(360.0)).degrees
            # The author's clockwise-positive angle becomes Garmin's
            # counter-clockwise one; a positive sweep therefore draws clockwise
            # on the device.  `shape: arc` calls the same helper.
            garmin_start, direction = garmin_arc(start, sweep)
            return PlacedProgress(
                element, box.rounded(), (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                garmin_start=garmin_start,
                garmin_direction=direction,
            )
        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        box = Box(cx - width / 2, cy - height / 2, width, height)
        return PlacedProgress(element, box.rounded(), (round(cx), round(cy)), depth,
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
        box = Box(cx - width / 2, cy - height / 2, width, height)
        return PlacedIcon(
            element, box.rounded(), (round(cx), round(cy)), depth,
            size=px, font_key=key, codepoint=measure_codepoint,
            anchor_point=(round(cx), round(cy)),
        )

    def _resolve_graph(self, element: Graph, parent: Box, depth: int) -> Placed:
        cx, cy = self._point(element.at, parent)
        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        box = Box(cx - width / 2, cy - height / 2, width, height)
        thickness = max(1, round(self._len(element.thickness, parent, Axis.MINOR, 2)))
        bar_width = max(1, round(self._len(element.bar_width, parent, Axis.MINOR, 3)))
        return PlacedGraph(
            element, box.rounded(), (round(cx), round(cy)), depth,
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
        (the declared choices plus any per-choice override, or -- since
        2026-09-13 -- the whole of `wfb.icons.COMPLICATION_ICON` for
        `choices: any`), keyed by this slot's own name so two different
        slots never collide into one font resource.

        The estimated box's extent, for any `icon_position:`, comes from
        `complication_slot_pair_geometry` -- the one place this geometry is
        computed (plan 03 §6.3) -- using `icon_px` (the *declared* visual
        icon height, not the measured glyph height) as the icon's height,
        matching this element's own long-standing `left`-position height
        estimate (`max(line_height, icon_px, 1)`) so a design that changes
        none of `icon_position:`/`icon_gap:` keeps generating the exact same
        numbers it did before either key existed.
        """
        cx, cy = self._point(element.at, parent)
        font_px, reference, is_custom, baked = self._font_for(element)
        widest = self._complication_slot_widest(element)
        if baked is not None:
            text_width, line_height = baked.measure(widest)
        else:
            text_width, _ = fallback.measure(widest, font_px)
            line_height = font_px

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
        box = Box(cx - geometry.width / 2, cy - height / 2, geometry.width, height)
        return PlacedComplicationSlot(
            element, box.rounded(), (round(cx), round(cy)), depth,
            anchor_point=(round(cx), round(cy)),
            font_reference=reference, font_is_custom=is_custom, font_px=font_px,
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
            if len(candidate) > len(widest):
                widest = candidate
        if element.when_absent == "placeholder" and element.placeholder:
            if len(element.placeholder) > len(widest):
                widest = element.placeholder
        # `label:`/`unit:` are deliberately NOT folded in here, unlike the
        # digit-count estimate above: `Complication.shortLabel`/`.longLabel`
        # and a String `.unit` are localised device strings with no
        # documented upper bound at all (unlike a digit count, which at
        # least has a plausible ceiling), so *any* fixed padding here is a
        # guess that would either be routinely wrong or -- picked large
        # enough to rarely be wrong -- inflate every ordinary slot's box
        # into a spurious `off-screen` build **error** (checked directly:
        # an 8-character placeholder pushed a design that fits comfortably
        # off the framebuffer). `docs/limitations.md` records this as a
        # documented gap instead: the geometry/overflow checks size a
        # slot's box from its value alone.
        return widest

    def _resolve_hands(self, element: HandsElement, parent: Box, depth: int) -> Placed:
        """`type: hands` -- the axis, plus every part of every declared hand
        resolved to whole pixels in the hand's own frame (plan 04 §5.3,
        §5.8).  The rotation itself is the one piece of layout arithmetic
        the *device* performs (ADR 0004, amended) -- everything here is
        still a build-time constant.
        """
        cx, cy = self._point(element.at, parent)
        hand_set = self.face.hands[element.hands]
        resolved: dict[str, ResolvedHand] = {}
        reach = 0.0
        for name, hand in hand_set.hands():
            if name == "second" and element.seconds == "never":
                # "the set's second hand is not drawn at all" (§5.6) -- left
                # unresolved, exactly as if the set declared no `second:` at
                # all, so codegen's `if hand is None: continue` already
                # covers it with no extra check, and its geometry does not
                # inflate the swept disc's reach (§5.8: "any part of any
                # *drawn* hand").
                continue
            parts = []
            for part in hand.parts:
                resolved_part, part_reach = self._resolve_hand_part(part)
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
        self, part, element_id: str = "", part_index: int = -1,
    ) -> tuple[ResolvedHandPart, float]:
        """One hand part -> whole-pixel geometry in the hand's own frame,
        plus its own reach from the axis (the farthest ink any of its
        drawing touches).  Rounds with :func:`_round_away`, not the plain
        `round()` every other element here uses -- §5.3's mirror-symmetry
        rule is specific to a hand frame, which is the only geometry a
        symmetric pair of authored coordinates (`dx: -1.5px`/`dx: 1.5px`)
        can appear in.

        `element_id`/`part_index` are used only by a `shape: text` part
        (plan 06 §3.4, reachable only through a pattern's template, never a
        hand's -- `wfb.ir.HAND_PART_REJECTED_SHAPES` still refuses it), to
        name the part in `_font_for_ref`'s "no pixel metrics" warning the
        same way `check_glyphs` names one (`hours.parts[0]`); every other
        caller (every hand part) leaves them at their default and never
        reaches a code path that reads them.
        """
        if part.shape == "polygon":
            points = tuple(
                (_round_away(x), _round_away(y))
                for x, y in (self._hand_point(p) for p in part.points)
            )
            reach = max((math.hypot(x, y) for x, y in points), default=0.0)
            return ResolvedHandPart("polygon", part.color, points=points), reach

        if part.shape == "rectangle":
            cx, cy = self._hand_point(part.at)
            width = self._hand_len(part.size.width)
            height = self._hand_len(part.size.height)
            hw, hh = width / 2.0, height / 2.0
            # top-left, top-right, bottom-right, bottom-left (§6) -- the same
            # corner order a rotated rectangle keeps no matter which corner
            # ends up where once the device rotates it.
            corners = [
                (cx - hw, cy - hh), (cx + hw, cy - hh),
                (cx + hw, cy + hh), (cx - hw, cy + hh),
            ]
            points = tuple((_round_away(x), _round_away(y)) for x, y in corners)
            reach = max(math.hypot(x, y) for x, y in points)
            return ResolvedHandPart("polygon", part.color, points=points), reach

        if part.shape == "line":
            x1, y1 = self._hand_point(part.at)
            x2, y2 = self._hand_point(part.to)
            thickness = max(1, _round_away(self._hand_len(part.thickness, default=1)))
            reach = max(math.hypot(x1, y1), math.hypot(x2, y2)) + thickness / 2.0
            return ResolvedHandPart(
                "line", part.color,
                x1=_round_away(x1), y1=_round_away(y1),
                x2=_round_away(x2), y2=_round_away(y2),
                thickness=thickness,
            ), reach

        if part.shape == "arc":
            # A hand never produces this shape (rejected in `wfb.ir`); a
            # pattern's template does (plan 05 §5.2).  Always centred on the
            # origin (x=y=0, D3), so its reach is exactly the pen's own
            # extent -- no `at:` to add a distance-from-origin term.
            radius = _round_away(self._hand_len(part.radius))
            thickness = max(1, _round_away(self._hand_len(part.thickness, default=1)))
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
            # only thing that goes through `_hand_point` (§3.4); the glyphs
            # themselves are measured, not rotated. `reach` is always `0.0`
            # here: text is not rotation-invariant, so `Resolver.
            # _resolve_pattern`'s per-copy loop computes the real farthest
            # corner instead (plan 06 §3.4).
            x0, y0 = self._hand_point(part.at)
            x, y = _round_away(x0), _round_away(y0)
            warn_id = f"{element_id}.parts[{part_index}]" if part_index >= 0 else element_id
            font_px, reference, is_custom, baked = self._font_for_ref(
                part.font, part.font_is_custom, warn_id)
            if baked is not None:
                widths = tuple(baked.measure(t)[0] for t in part.texts)
                line_height = baked.line_height
            else:
                widths = tuple(fallback.measure(t, font_px)[0] for t in part.texts)
                line_height = font_px
            justify = self._justify(part)
            return ResolvedHandPart(
                "text", part.color, x=x, y=y,
                font_reference=reference, font_is_custom=is_custom, font_px=font_px,
                justify=justify, align=part.align, vertical_align=part.vertical_align,
                line_height=line_height, texts=part.texts, widths=widths,
            ), 0.0

        # circle
        cx, cy = self._hand_point(part.at)
        radius = _round_away(self._hand_len(part.radius))
        thickness = max(1, _round_away(self._hand_len(part.thickness, default=1)))
        pen_reach = radius if part.filled else radius + thickness / 2.0
        reach = math.hypot(cx, cy) + pen_reach
        return ResolvedHandPart(
            "circle", part.color,
            x=_round_away(cx), y=_round_away(cy), radius=radius,
            thickness=thickness, filled=part.filled,
        ), reach

    def _resolve_pattern(self, element: PatternElement, parent: Box, depth: int) -> Placed:
        """`type: pattern` -- the template resolved once, in its own frame
        (`_resolve_hand_part`, reused: a pattern part is authored exactly
        like a hand part, plan 05 §5.2), plus which copies are drawn and the
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
        to every drawn copy's ink (§5.5).

        A `shape: text` part breaks the "rotation-invariant" half of that
        shortcut (plan 06 §3.4): upright glyphs are not the same distance
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
            resolved_part, part_reach = self._resolve_hand_part(part, element.id, part_index)
            parts.append(resolved_part)
            reach = max(reach, part_reach)

        if element.pattern == "radial":
            start, step = element.start_angle, element.step_angle
            dx = dy = 0
        else:
            start = step = 0.0
            reach = 0.0  # only a radial pattern reports a disc (§5.5)
            step_position = element.step or Position()
            dx = _round_away(self._len(step_position.dx, parent, Axis.X, 0))
            dy = _round_away(self._len(step_position.dy, parent, Axis.Y, 0))

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
            for part in parts:
                lo_x, lo_y, hi_x, hi_y = _pattern_part_ink(part, ox, oy, sin_t, cos_t, index)
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
        anchor to at all -- §5.1, §5.8)."""
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

    def _unbaked_font_size(self, spec: FontSpec) -> int:
        """The size to assume for a custom font that was not baked.

        A real build always bakes every declared font, so this is the path a
        caller who resolved layout with an empty ``fonts`` dict takes -- a unit
        test, or a geometry-only pass.  `size:` is always a `Length` now, and
        its unit already refers to this device, so it resolves exactly here.
        """
        return spec.pixel_size(self.minor_radius)

    def _font_for(self, element: Text) -> tuple[int, str, bool, BakedFont | None]:
        return self._font_for_ref(element.font, element.font_is_custom, element.id)

    def _font_for_ref(
        self, font: str, font_is_custom: bool, warn_id: str,
    ) -> tuple[int, str, bool, BakedFont | None]:
        """The shared body of `_font_for`, taking a bare `font:`/`font_is_
        custom` pair instead of a `Text` element -- what lets a `shape:
        text` pattern part (`Resolver._resolve_hand_part`, plan 06 §3.4)
        resolve its font through the exact same lookup and the exact same
        "no pixel metrics" warning `_font_for` already gives a `Text`
        element, with no second copy of either.
        """
        if font_is_custom:
            baked = self.fonts.get(font)
            spec = self.face.fonts[font]
            return (baked.size if baked else self._unbaked_font_size(spec)), \
                font, True, baked
        metric = self.device.system_fonts.get(font)
        size = metric.size_px if metric else 0
        if metric is None:
            self.warnings.append(
                f"{warn_id}: no pixel metrics for {font} on {self.device.id}; "
                f"text extent is not checked"
            )
        return size, font, False, None

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
            if len(element.placeholder) > len(widest):
                widest = element.placeholder
        if element.when_absent == "fallback" and element.fallback is not None:
            # 'fallback:' is drawn through the exact same format spec as the
            # real value (see _emit_text in wfb.emit.monkeyc), so its widest
            # rendering has to be considered too -- otherwise a font baked
            # from the *value*'s digit range alone can come up short for a
            # wider fallback (e.g. a longer literal string on a nullable
            # STRING source).
            fallback_widest = _fallback_widest(element.fallback, spec)
            if len(fallback_widest) > len(widest):
                widest = fallback_widest
        return widest

    @staticmethod
    def _justify(element: Text | HandPart) -> tuple[str, ...]:
        """`Toybox.Graphics.TEXT_JUSTIFY_*` flags for anything with `.align`/
        `.vertical_align` -- a `Text` element, or (plan 06 §3.4) a `shape:
        text` pattern part, which carries the same two fields under the
        same names.
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


def _fallback_widest(fallback_expr: Expression, spec: str) -> str:
    """The widest string a `fallback:` expression could render, through the
    same format spec the bound value uses (see Bug 1's `_emit_text`).

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
    "inside_visible_area_for", "circular_extent", "garmin_arc",
    "alignment_shift",
    "is_full_bleed",
    "ANCHORS", "Size",
]
