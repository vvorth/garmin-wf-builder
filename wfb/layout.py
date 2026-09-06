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

from . import catalog, formatting, icons
from .devices import Device
from .fonts import BakedFont, fallback
from .ir import (
    Element, Face, Group, IconElement, Position, Progress, Shape, Size, Text,
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


@dataclass
class PlacedShape(Placed):
    radius: int = 0
    corner_radius: int = 0
    thickness: int = 1
    end: tuple[int, int] = (0, 0)


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
    #: The requested pixel size (the font this icon was baked into is exactly
    #: this size -- there is no separate "natural" glyph size to distinguish
    #: it from).
    size: int = 0
    #: The synthetic font resource this icon draws from (see `wfb.icons.font_key`).
    font_key: str = ""
    #: The glyph itself, resolved from `element.icon` (a catalogue name or a
    #: literal character) at IR-build time.
    codepoint: str = "?"
    anchor_point: tuple[int, int] = (0, 0)


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
        self.items.sort(key=lambda p: (p.element.z if p.element.z is not None else 0,))
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

        width = self._len(element.size.width, parent, Axis.X, parent.width)
        height = self._len(element.size.height, parent, Axis.Y, parent.height)
        corner = round(self._len(element.corner_radius, parent, Axis.MINOR, 0))
        box = Box(cx - width / 2, cy - height / 2, width, height)
        return PlacedShape(element, box.rounded(), (round(cx), round(cy)), depth,
                           corner_radius=corner, thickness=max(1, thickness))

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
            return PlacedProgress(
                element, box.rounded(), (round(cx), round(cy)), depth,
                radius=radius, thickness=thickness,
                start_angle=start, sweep=sweep,
                # The author's clockwise-positive angle becomes Garmin's
                # counter-clockwise one; a positive sweep therefore draws
                # clockwise on the device.
                garmin_start=(90.0 - start) % 360.0,
                garmin_direction="ARC_CLOCKWISE" if sweep >= 0 else "ARC_COUNTER_CLOCKWISE",
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
        # one (ADR-equivalent reasoning in wfb.icons.pixel_size).
        px = icons.pixel_size(element.size, self.device.minor_radius)
        key = icons.font_key(element.size)
        font = self.fonts.get(key)
        if font is not None:
            width, height = font.measure(element.codepoint)
        else:
            width = height = px  # the font failed to bake; keep a plausible box
        box = Box(cx - width / 2, cy - height / 2, width, height)
        return PlacedIcon(
            element, box.rounded(), (round(cx), round(cy)), depth,
            size=px, font_key=key, codepoint=element.codepoint,
            anchor_point=(round(cx), round(cy)),
        )

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

    def _font_for(self, element: Text) -> tuple[int, str, bool, BakedFont | None]:
        if element.font_is_custom:
            baked = self.fonts.get(element.font)
            spec = self.face.fonts[element.font]
            return (baked.size if baked else round(spec.size)), element.font, True, baked
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


def resolve(face: Face, device: Device, fonts: dict[str, BakedFont]) -> ResolvedFace:
    return Resolver(face, device, fonts).resolve()


def font_pixel_size(spec_size: float, device: Device, reference_minor: float) -> int:
    """Scale a declared font size to this device's screen (ADR 0004 3b).

    A sheet baked for 260x260 is wrong on the 280x280 fenix 8 Solar 51 mm -- the
    drift the sibling Dashboard project already has by hand.  Scaling by the
    minor screen dimension keeps one declaration correct on both.
    """
    return max(6, round(spec_size * (device.minor_radius / reference_minor)))


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
    if isinstance(placed, PlacedShape) and placed.element.shape == "circle":
        reach = placed.radius + (0 if placed.element.filled else placed.thickness / 2.0)
        return (placed.center[0], placed.center[1], reach)
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
    "ResolvedFace", "resolve", "safe_area", "inside_screen", "inside_visible_area",
    "inside_visible_area_for", "circular_extent",
    "is_full_bleed", "font_pixel_size",
    "ANCHORS", "Size",
]
