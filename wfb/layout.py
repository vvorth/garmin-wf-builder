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
    Carousel, ComplicationSlot, Element, Expression, Face, FontSpec, Graph, Group,
    IconElement, Position, Progress, Shape, Size, Text, draw_sort_key,
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
class PlacedCarouselItem:
    """One slot's resolved drawing data.  Index is its position in `items:`."""

    index: int
    #: The synthetic icon font this item's glyph draws from (`wfb.icons.font_key`).
    font_key: str
    codepoint: str
    #: The widest reading this item can render, for the value font's glyph set
    #: and for the overflow check.
    widest: str = ""


@dataclass
class PlacedCarousel(Placed):
    """A carousel, resolved: the icon row, the reading, and the three zones.

    The zone edges are resolved here rather than in the emitter for the same
    reason every other coordinate is (ADR 0004): the device does no layout
    arithmetic, and `wfb preview` can draw the same boundaries the delegate
    tests against.
    """

    items: list[PlacedCarouselItem] = field(default_factory=list)
    #: Centre of the icon row.
    row_center: tuple[int, int] = (0, 0)
    pitch: int = 0
    icon_px: int = 0
    #: Where the selected item's reading is drawn.
    value_anchor: tuple[int, int] = (0, 0)
    value_font_reference: str = "FONT_SMALL"
    value_font_is_custom: bool = False
    value_font_px: int = 0
    value_widest: str = ""
    value_measured_width: int = 0
    value_width_is_estimated: bool = False
    #: x < this is "previous"; x >= `next_edge` is "next"; between them is
    #: "open this item's glance".
    prev_edge: int = 0
    next_edge: int = 0
    #: What the element actually *paints* -- the icon row plus the reading --
    #: which is narrower than `box`.  `box` is the touch target, and an author
    #: sizing that generously is not a layout mistake, so the visible-area
    #: check reads this instead (see `wfb.lint.check_geometry`); reachability
    #: of the zones is its own question, asked by `check_carousel_zones`.
    content_box: IntBox | None = None


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


#: Fixed pixel gap between a complication_slot's icon and its reading.  A
#: small constant rather than a fraction of the icon's own size, the same way
#: `PlacedShape`'s outline padding is a fixed `+1`/`+2` rather than scaled --
#: there is no `size:`-like key in the format to derive one from, and getting
#: this exact does not change what the element *is*.
COMPLICATION_SLOT_ICON_GAP = 4


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
    #: entry in `wfb.icons.COMPLICATION_ICON`.
    icon_font_key: str | None = None
    icon_px: int = 0


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

    def clip_for(self, mode: str) -> IntBox | None:
        """The tightest rectangle covering everything drawn in ``mode``.

        ``setClip`` is charged by *region area* -- every pixel in the clip counts
        as modified whenever any does -- so this being tight is what keeps
        ``onPartialUpdate`` inside its budget.
        """
        boxes = [p.box for p in self.in_mode(mode)]
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
            elif isinstance(element, Carousel):
                self.items.append(self._resolve_carousel(element, parent, depth))
            elif isinstance(element, Graph):
                self.items.append(self._resolve_graph(element, parent, depth))
            elif isinstance(element, ComplicationSlot):
                self.items.append(self._resolve_complication_slot(element, parent, depth))

    # -- per-kind ---------------------------------------------------------

    def _group_box(self, element: Group, parent: Box) -> Box:
        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        cx, cy = self._point(element.at, parent)
        return Box(cx - width / 2, cy - height / 2, width, height)

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
        left = {"left": x, "center": x - width / 2, "right": x - width}[element.align]
        if element.vertical_align == "center":
            top = y - line_height / 2
        elif element.vertical_align == "top":
            top = y
        else:  # baseline
            top = y - line_height
        box = Box(left, top, width, line_height)
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

    def _resolve_carousel(self, element: Carousel, parent: Box, depth: int) -> Placed:
        """Resolve the icon row, the reading, and the three hold zones.

        The element's own box is the hit region *and* the drawn extent, so it
        is taken from `size:` rather than derived from the icons -- an author
        sizing the touch target is doing something the compiler cannot infer,
        and a box that stops at the icons would make the outer zones
        unreachably narrow.
        """
        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        cx, cy = self._point(element.at, parent)
        box = Box(cx - width / 2, cy - height / 2, width, height)

        icon_px = units.pixel_size(element.icon_size, self.device.minor_radius)
        pitch = round(self._len(element.pitch, box, Axis.X,
                                width / max(1, element.slots)))

        placed_items: list[PlacedCarouselItem] = []
        for index, item in enumerate(element.items):
            key = icons.font_key(element.icon_size, item.codepoint, element.resolved_antialias)
            placed_items.append(PlacedCarouselItem(
                index=index, font_key=key, codepoint=item.codepoint,
                widest=_carousel_item_widest(item),
            ))

        font_px, reference, is_custom, baked = self._carousel_value_font(element)
        widest = max((i.widest for i in placed_items), key=len, default="")
        if baked is not None:
            value_width, _ = baked.measure(widest)
            estimated = False
        else:
            value_width, _ = fallback.measure(widest, font_px)
            estimated = True

        offset = element.value_offset or Position(anchor="center", dy=None)
        vx, vy = self._point(offset, box)

        # Three equal zones across the box.  Equal because the alternative --
        # sizing the outer zones to the neighbouring icons -- would make them
        # shrink exactly when the row is dense and a miss costs most.
        third = width / 3.0
        # The drawn extent: the icon row, plus the reading where there is one.
        # Deliberately not `box`, which is the touch target -- see
        # PlacedCarousel.content_box.
        reach = element.slots // 2
        content_half = reach * pitch + max(icon_px, 1) / 2.0
        left, right = cx - content_half, cx + content_half
        top, bottom = cy - icon_px / 2.0, cy + icon_px / 2.0
        if widest:
            value_height = max(font_px, 1)
            left = min(left, vx - value_width / 2.0)
            right = max(right, vx + value_width / 2.0)
            top = min(top, vy - value_height / 2.0)
            bottom = max(bottom, vy + value_height / 2.0)
        content = Box(left, top, right - left, bottom - top)
        return PlacedCarousel(
            element, box.rounded(), (round(cx), round(cy)), depth,
            items=placed_items,
            row_center=(round(cx), round(cy)),
            pitch=pitch,
            icon_px=icon_px,
            value_anchor=(round(vx), round(vy)),
            value_font_reference=reference,
            value_font_is_custom=is_custom,
            value_font_px=font_px,
            value_widest=widest,
            value_measured_width=round(value_width),
            value_width_is_estimated=estimated,
            prev_edge=round(box.x + third),
            next_edge=round(box.x + 2 * third),
            content_box=content.rounded(),
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
        multi-glyph icon font covering every declared choice that has an
        entry in `wfb.icons.COMPLICATION_ICON`, keyed by this slot's own name
        so two different slots never collide into one font resource.
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
            if slot is not None and not slot.allow_any:
                mapped = {name: icons.COMPLICATION_ICON[name] for name in slot.choices
                         if name in icons.COMPLICATION_ICON}
                if mapped:
                    icon_name = mapped.get(slot.default) or sorted(mapped.values())[0]
                    reference_glyph = icons.CATALOG[icon_name].codepoint
            if reference_glyph is not None:
                icon_px = units.pixel_size(element.icon_size, self.device.minor_radius)
                icon_font_key = icons.font_key(
                    element.icon_size, f"slot_{element.slot}", element.resolved_antialias)
                font = self.fonts.get(icon_font_key)
                if font is not None:
                    icon_width, _ = font.measure(reference_glyph)
                else:
                    icon_width = icon_px

        total_width = text_width + (icon_width + COMPLICATION_SLOT_ICON_GAP if icon_font_key else 0)
        height = max(line_height, icon_px, 1)
        box = Box(cx - total_width / 2, cy - height / 2, total_width, height)
        return PlacedComplicationSlot(
            element, box.rounded(), (round(cx), round(cy)), depth,
            anchor_point=(round(cx), round(cy)),
            font_reference=reference, font_is_custom=is_custom, font_px=font_px,
            widest=widest, icon_font_key=icon_font_key, icon_px=icon_px,
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

    def _carousel_value_font(self, element: Carousel) -> tuple[int, str, bool, BakedFont | None]:
        if element.value_font_is_custom:
            baked = self.fonts.get(element.value_font)
            spec = self.face.fonts[element.value_font]
            return ((baked.size if baked else self._unbaked_font_size(spec)),
                    element.value_font, True, baked)
        metric = self.device.system_fonts.get(element.value_font)
        if metric is None:
            self.warnings.append(
                f"{element.id}: no pixel metrics for {element.value_font} on "
                f"{self.device.id}; the reading's extent is not checked"
            )
            return 0, element.value_font, False, None
        return metric.size_px, element.value_font, False, None

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
        test, or a geometry-only pass.  A `Length` size resolves exactly here,
        since its unit already refers to this device; a bare number is taken
        verbatim, because the reference device it would scale against is a
        property of the *target list*, which is not in scope.  Unchanged from
        before `size:` grew the `Length` spelling.
        """
        return spec.pixel_size(self.minor_radius)

    def _font_for(self, element: Text) -> tuple[int, str, bool, BakedFont | None]:
        if element.font_is_custom:
            baked = self.fonts.get(element.font)
            spec = self.face.fonts[element.font]
            return (baked.size if baked else self._unbaked_font_size(spec)), \
                element.font, True, baked
        metric = self.device.system_fonts.get(element.font)
        size = metric.size_px if metric else 0
        if metric is None:
            self.warnings.append(
                f"{element.id}: no pixel metrics for {element.font} on {self.device.id}; "
                f"text extent is not checked"
            )
        return size, element.font, False, None

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
    def _justify(element: Text) -> tuple[str, ...]:
        flags = {
            "left": "TEXT_JUSTIFY_LEFT",
            "center": "TEXT_JUSTIFY_CENTER",
            "right": "TEXT_JUSTIFY_RIGHT",
        }[element.align]
        out = [flags]
        if element.vertical_align == "center":
            out.append("TEXT_JUSTIFY_VCENTER")
        return tuple(out)


def _carousel_item_widest(item) -> str:
    """The widest reading one carousel item can draw.

    Same reasoning as :meth:`Resolver._widest_text` -- the substitute a
    `placeholder:`/`fallback:` policy supplies is drawn through the same
    format spec as the real value, so it has to be considered when sizing the
    row and when subsetting the value font.
    """
    if item.value is None:
        return ""
    source = catalog.get(item.value.sources[0]) if item.value.sources else None
    spec = item.format or "{}"
    widest = formatting.widest(spec, source, item.value.value.type, item.value.scale)
    if item.when_absent == "placeholder" and item.placeholder:
        if len(item.placeholder) > len(widest):
            widest = item.placeholder
    if item.when_absent == "fallback" and item.fallback is not None:
        substitute = _fallback_widest(item.fallback, spec)
        if len(substitute) > len(widest):
            widest = substitute
    return widest


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
    return None


def inside_visible_area_for(placed: "Placed", device: Device) -> bool | None:
    """Visibility test that respects the element's actual shape.

    A carousel is the one element whose `box` is deliberately larger than what
    it paints -- the box is its touch target, and sizing that generously is a
    choice, not a mistake -- so it is checked against `content_box` instead.
    Whether the *zones* inside that generous box are actually reachable is a
    different question, and `wfb.lint.check_carousel_zones` asks it.
    """
    content = getattr(placed, "content_box", None)
    if content is not None:
        return inside_visible_area(content, device)
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
    "PlacedCarousel", "PlacedCarouselItem", "PlacedGraph", "PlacedComplicationSlot",
    "ResolvedFace", "resolve", "safe_area", "inside_screen", "inside_visible_area",
    "inside_visible_area_for", "circular_extent", "garmin_arc",
    "is_full_bleed",
    "ANCHORS", "Size",
]
