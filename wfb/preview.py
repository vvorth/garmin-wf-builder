"""Host-side preview: render a resolved design to a PNG.

ADR 0004: the preview renderer consumes the **same resolved IR** the code
generator does, so preview and device cannot disagree about position.  That is
the anti-drift mechanism, and it works only because layout is resolved before
codegen rather than on the watch.

It also runs with no Garmin toolchain and no simulator, which matters: the
simulator needs a GUI, and in a headless container it is unavailable.

What the preview does *not* claim: it is not a firmware-accurate renderer.
Anti-aliasing, the exact arc cap shape and the transflective panel's real
appearance are approximations, and the header on every image says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from . import catalog, expr, formatting
from .catalog import Type
from .fonts import BakedFont, fallback
from .ir import Carousel, Progress, Shape, Text
from .layout import (
    PlacedCarousel, PlacedGraph, PlacedIcon, PlacedProgress, PlacedShape, PlacedText,
    ResolvedFace,
)
from .palette import MIP64_LEVELS, Color

#: Plausible readings, so a preview shows a face mid-life rather than at zero.
SAMPLE: dict[str, object] = {
    "time.clock": 0,
    "date.today": 0,
    "date.weekday": "Wed",
    "date.day": 3,
    "date.month": "Sep",
    "date.month_number": 9,
    "date.year": 2026,
    "time.hour": 10,
    "time.minute": 9,
    "time.second": 42,
    "device.is_24_hour": True,
    "device.do_not_disturb": False,
    "device.notification_count": 3,
    "device.alarm_count": 1,
    "device.phone_connected": True,
    "system.battery": 68.0,
    "system.battery_in_days": 9.0,
    "system.charging": False,
    "activity.steps": 8432,
    "activity.step_goal": 10000,
    "activity.calories": 1840,
    "activity.distance": 631000,
    "activity.floors_climbed": 7,
    "activity.floors_climbed_goal": 10,
    "activity.move_bar_level": 2,
    "activity.active_minutes_week": 96,
    "activity.active_minutes_week_goal": 150,
    "heart_rate.current": 72,
}


@dataclass
class PreviewOptions:
    scale: int = 2
    #: Snap every colour to the device's real palette, so a dithered colour
    #: looks wrong in the preview the way it will look wrong on the wrist.
    quantise: bool = True
    #: Render the bezel crop, so an element under it is visibly cut.
    mask_shape: bool = True
    sample: dict[str, object] | None = None


def render(resolved: ResolvedFace, options: PreviewOptions | None = None) -> Image.Image:
    options = options or PreviewOptions()
    values = dict(SAMPLE)
    if options.sample:
        values.update(options.sample)

    # Palette entries are ordinary references inside an expression, so a
    # conditional colour cannot be evaluated without them.  Seeding them here is
    # what makes `cond ? palette.a : palette.b` render as the design intends
    # rather than silently falling back to white.
    for name, color in resolved.face.palette.items():
        values.setdefault(f"palette.{name}", color.value)

    # `config:` entries render at their declared defaults -- the preview has
    # no on-device editor to ask, and the default is the only value a target
    # without one (fr955) ever shows anyway (ADR 0006 1).
    for name, entry in resolved.face.config.items():
        values.setdefault(f"config.{name}", entry.default.value)

    device = resolved.device
    scale = max(1, options.scale)
    size = (device.width * scale, device.height * scale)
    image = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(image)

    renderer = _Renderer(resolved, draw, image, scale, values, options)
    for placed in resolved.items:
        if placed.kind == "group":
            continue
        if "active" not in placed.element.modes:
            continue
        renderer.render_element(placed)

    if options.quantise and device.display_colors == 64:
        image = _quantise_mip64(image)
    if options.mask_shape and device.shape == "round":
        image = _mask_round(image, scale)
    return image


class _Renderer:
    def __init__(self, resolved, draw, image, scale, values, options) -> None:
        self.resolved = resolved
        self.draw = draw
        self.image = image
        self.scale = scale
        self.values = values
        self.options = options

    # -- dispatch ---------------------------------------------------------

    def render_element(self, placed) -> None:
        if not self._visible(placed):
            return
        if isinstance(placed, PlacedShape):
            self._shape(placed)
        elif isinstance(placed, PlacedText):
            self._text(placed)
        elif isinstance(placed, PlacedProgress):
            self._progress(placed)
        elif isinstance(placed, PlacedIcon):
            self._icon(placed)
        elif isinstance(placed, PlacedCarousel):
            self._carousel(placed)
        elif isinstance(placed, PlacedGraph):
            self._graph(placed)

    # -- elements ---------------------------------------------------------

    def _shape(self, placed: PlacedShape) -> None:
        element = placed.element
        fill = self._color(element.color)
        s = self.scale
        if element.shape == "rectangle":
            box = self._rect(placed.rect or placed.box)
            if element.filled:
                self.draw.rectangle(box, fill=fill)
            else:
                self.draw.rectangle(box, outline=fill, width=max(1, placed.thickness * s))
        elif element.shape == "rounded_rectangle":
            box = self._rect(placed.rect or placed.box)
            radius = placed.corner_radius * s
            if element.filled:
                self.draw.rounded_rectangle(box, radius=radius, fill=fill)
            else:
                self.draw.rounded_rectangle(box, radius=radius, outline=fill,
                                            width=max(1, placed.thickness * s))
        elif element.shape == "arc":
            # Same conversion the generated code gets from WfbArc.drawSpan:
            # Pillow's arc runs clockwise from 3 o'clock, the format's angles run
            # clockwise from 12, so shift by 90 and order the endpoints so Pillow
            # takes the short way round -- exactly as `_progress` does.
            cx, cy = placed.center[0] * s, placed.center[1] * s
            r = placed.radius * s
            start = placed.start_angle - 90.0
            sweep = max(-359.9, min(359.9, placed.sweep))
            end = start + sweep
            a, b = (start, end) if sweep >= 0 else (end, start)
            if r > 0 and sweep != 0:
                self.draw.arc([cx - r, cy - r, cx + r, cy + r], a, b,
                              fill=fill, width=max(1, placed.thickness * s))
        elif element.shape == "ellipse":
            cx, cy = placed.center
            rx, ry = placed.rx, placed.ry
            box = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
            if element.filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, placed.thickness * s))
        elif element.shape == "polygon":
            if len(placed.points) >= 3:
                self.draw.polygon([(x * s, y * s) for x, y in placed.points], fill=fill)
        elif element.shape == "circle":
            cx, cy = placed.center
            r = placed.radius
            box = [(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s]
            if element.filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, placed.thickness * s))
        elif element.shape == "line":
            self.draw.line(
                [placed.center[0] * s, placed.center[1] * s, placed.end[0] * s, placed.end[1] * s],
                fill=fill, width=max(1, placed.thickness * s),
            )

    def _text(self, placed: PlacedText) -> None:
        element = placed.element
        text = self._text_value(placed)
        if text is None:
            return
        color = self._color(element.color)
        font: BakedFont | None = (
            self.resolved.fonts.get(placed.font_reference) if placed.font_is_custom else None
        )
        if font is not None:
            self._blit_bitmap_text(font, text, placed, color)
        else:
            self._approximate_text(text, placed, color)

    def _progress(self, placed: PlacedProgress) -> None:
        element = placed.element
        value = expr.evaluate(element.value.ast, self.values) if element.value.ast else None
        maximum = expr.evaluate(element.maximum.ast, self.values) if element.maximum.ast else None
        if value is None or maximum is None:
            if element.when_absent == "hide":
                return
            # `fallback:` on a progress substitutes the fill fraction itself,
            # not the value -- see wfb/emit/monkeyc.py's `_fallback_fraction`.
            # Rendering the same substitution the device does is what keeps
            # this preview and the generated code from disagreeing, which is
            # the whole reason the resolved geometry is shared.
            fraction = 0.0
            if element.when_absent == "fallback" and element.fallback is not None \
                    and element.fallback.ast is not None:
                substitute = expr.evaluate(element.fallback.ast, self.values)
                if substitute is not None:
                    fraction = min(1.0, max(0.0, float(substitute)))
        else:
            fraction = (
                0.0 if not maximum or maximum <= 0
                else min(1.0, max(0.0, value / maximum))
            )
        s = self.scale

        if element.style == "arc":
            cx, cy, r = placed.center[0] * s, placed.center[1] * s, placed.radius * s
            width = max(1, placed.thickness * s)
            box = [cx - r, cy - r, cx + r, cy + r]
            # Pillow's arc runs clockwise from 3 o'clock; the author's angles run
            # clockwise from 12 o'clock, so shift by 90 degrees.
            start = placed.start_angle - 90.0

            def span(sweep: float) -> tuple[float, float]:
                """Order the endpoints so Pillow takes the short way round."""
                end = start + sweep
                return (start, end) if sweep >= 0 else (end, start)

            if element.track_color is not None:
                a, b = span(placed.sweep)
                self.draw.arc(box, a, b, fill=self._color(element.track_color), width=width)
            if fraction > 0:
                a, b = span(placed.sweep * fraction)
                self.draw.arc(box, a, b, fill=self._color(element.color), width=width)
            return

        box = self._rect(placed.box)
        if element.track_color is not None:
            self.draw.rectangle(box, fill=self._color(element.track_color))
        filled = int(placed.box.width * fraction) * s
        if filled > 0:
            self.draw.rectangle([box[0], box[1], box[0] + filled, box[3]],
                                fill=self._color(element.color))

    def _icon(self, placed: PlacedIcon) -> None:
        """One glyph from the baked icon font -- the same mechanism a
        custom-font text element uses to draw, not a hand-drawn shape.  See
        ``wfb.icons``: this is what makes preview and device agree on an icon's
        appearance without a second, hand-maintained drawing implementation."""
        font = self.resolved.fonts.get(placed.font_key)
        sheet = getattr(font, "sheet_image", None) if font else None
        glyph = font.glyphs.get(placed.codepoint) if font else None
        if sheet is None or glyph is None:
            return  # the font failed to bake, or the glyph is missing from it
        s = self.scale
        color = self._color(placed.element.color)
        self._paste_glyph(sheet, glyph, placed.box.x * s, placed.box.y * s, color)

    def _graph(self, placed: PlacedGraph) -> None:
        """A synthetic series -- shape and placement only, never real data.

        There is no live `ActivityMonitor`/`Weather` history on the host, so
        this draws a deterministic stand-in sized to exactly the sample
        count the device will draw (`element.sample_count`, resolved at IR
        build time from `range:`/`buckets:` -- the same figure
        `wfb.emit.monkeyc` bakes into the generated acquisition call) --
        the honest analogue of the scalar `SAMPLE` table every other element
        already previews against. Geometry -- box, thickness, bar width --
        comes from the same resolved `PlacedGraph` the device draws from, so
        this is exactly the picture codegen produces, not a second guess at it.
        """
        element = placed.element
        values = _synthetic_series(max(0, element.sample_count))
        if element.min_auto:
            present = [v for v in values if v is not None]
            lo = min(present) if present else 0.0
        else:
            lo = self._graph_bound(element.min, 0.0)
        if element.max_auto:
            present = [v for v in values if v is not None]
            hi = max(present) if present else 1.0
        else:
            hi = self._graph_bound(element.max, 1.0)
        span = hi - lo
        if span <= 0:
            span = 1.0
        color = self._color(element.color)
        if element.style == "line":
            self._graph_line(placed, values, lo, span, color)
        elif element.style == "area":
            self._graph_area(placed, values, lo, span, color)
        else:
            self._graph_bars(placed, values, lo, span, color)

    def _graph_bound(self, expression, default: float) -> float:
        """A fixed `min:`/`max:` expression, evaluated against the same
        sample readings every other bound value previews against."""
        if expression is None or expression.ast is None:
            return default
        value = expr.evaluate(expression.ast, self.values)
        return default if value is None else float(value)

    def _graph_point(self, placed: PlacedGraph, i: int, n: int, value: float,
                     lo: float, span: float) -> tuple[float, float]:
        s = self.scale
        x, y = placed.box.x, placed.box.y
        w, h = placed.size
        cx = x + (i * w / (n - 1) if n > 1 else 0)
        cy = y + h - (value - lo) * h / span
        return cx * s, cy * s

    def _graph_line(self, placed: PlacedGraph, values: list[float | None],
                    lo: float, span: float, color) -> None:
        n = len(values)
        if n < 2:
            return
        s = self.scale
        previous = None
        for i, value in enumerate(values):
            if value is None:
                previous = None
                continue
            point = self._graph_point(placed, i, n, value, lo, span)
            if previous is not None:
                self.draw.line([previous, point], fill=color, width=max(1, placed.thickness * s))
            previous = point

    def _graph_area(self, placed: PlacedGraph, values: list[float | None],
                    lo: float, span: float, color) -> None:
        """One filled run per contiguous stretch of present samples -- the
        same "a gap must not draw" rule `WfbSeries.drawArea` follows, so a
        gap in the synthetic series (were one ever added) would look the
        same way here as it will on the wrist."""
        n = len(values)
        if n < 2:
            return
        s = self.scale
        x, y = placed.box.x, placed.box.y
        w, h = placed.size
        i = 0
        while i < n:
            if values[i] is None:
                i += 1
                continue
            run: list[tuple[float, float]] = []
            while i < n and values[i] is not None:
                run.append(self._graph_point(placed, i, n, values[i], lo, span))
                i += 1
            if len(run) >= 2:
                bottom = (y + h) * s
                polygon = run + [(run[-1][0], bottom), (run[0][0], bottom)]
                self.draw.polygon(polygon, fill=color)

    def _graph_bars(self, placed: PlacedGraph, values: list[float | None],
                    lo: float, span: float, color) -> None:
        n = len(values)
        if n < 1:
            return
        s = self.scale
        x, y = placed.box.x, placed.box.y
        w, h = placed.size
        pitch = w / n
        for i, value in enumerate(values):
            if value is None:
                continue
            bar_height = max(1, round((value - lo) * h / span))
            left = (x + i * pitch + (pitch - placed.bar_width) / 2) * s
            top = (y + h - bar_height) * s
            self.draw.rectangle(
                [left, top, left + placed.bar_width * s - 1, (y + h) * s - 1], fill=color
            )

    def _carousel(self, placed: PlacedCarousel) -> None:
        """The carousel as the wearer would first see it: item 0 centred.

        A preview cannot show a selection the wearer has not made yet, and
        guessing one would make the image disagree with the watch on first
        launch.  `Application.Storage` starts empty, `WfbCarousel.restore`
        returns 0, so item 0 is what the device actually draws.
        """
        element = placed.element
        if not placed.items:
            return
        s = self.scale
        count = len(placed.items)
        reach = element.slots // 2
        active = self._color(element.color)
        inactive = (self._color(element.inactive_color)
                    if element.inactive_color is not None else active)

        for slot in range(-reach, reach + 1):
            item = placed.items[slot % count]
            font = self.resolved.fonts.get(item.font_key)
            sheet = getattr(font, "sheet_image", None) if font else None
            glyph = font.glyphs.get(item.codepoint) if font else None
            if sheet is None or glyph is None:
                continue
            cx = placed.row_center[0] + slot * placed.pitch
            width, height = font.measure(item.codepoint)
            self._paste_glyph(sheet, glyph,
                              (cx - width / 2) * s,
                              (placed.row_center[1] - height / 2) * s,
                              active if slot == 0 else inactive)

        text = self._carousel_value(element.items[0])
        if not text:
            return
        color = (self._color(element.value_color)
                 if element.value_color is not None else active)
        value_font = (self.resolved.fonts.get(placed.value_font_reference)
                      if placed.value_font_is_custom else None)
        reading = PlacedText(
            element=element, box=placed.box, center=placed.value_anchor,
            anchor_point=placed.value_anchor,
            justify=("TEXT_JUSTIFY_CENTER", "TEXT_JUSTIFY_VCENTER"),
            font_reference=placed.value_font_reference,
            font_is_custom=placed.value_font_is_custom,
            font_px=placed.value_font_px,
            widest=placed.value_widest,
            measured_width=placed.value_measured_width,
        )
        if value_font is not None:
            self._blit_bitmap_text(value_font, text, reading, color)
        else:
            self._approximate_carousel_value(text, reading, color)

    def _approximate_carousel_value(self, text: str, reading: PlacedText, color) -> None:
        """`_approximate_text` reads `align`/`vertical_align` off the element,
        which a carousel does not have -- its reading is always centred on its
        own anchor.  Same stand-in face, same measured extent."""
        s = self.scale
        face = fallback.font_for_height(reading.font_px * s)
        if face is None:
            return
        self.draw.text((reading.anchor_point[0] * s, reading.anchor_point[1] * s),
                       text, fill=color, font=face, anchor="mm")

    def _carousel_value(self, item) -> str:
        """One item's reading, applying the same `when_absent:` the device does."""
        if item.value is None:
            return ""
        spec = item.format or "{}"
        if item.value.value.type is Type.TIME:
            return _render_time(spec, self.values)
        if item.value.value.type is Type.DATE:
            return _render_date(spec, self.values)
        value = expr.evaluate(item.value.ast, self.values) if item.value.ast else None
        if value is None:
            if item.when_absent == "placeholder":
                return item.placeholder or ""
            if item.when_absent == "fallback" and item.fallback and item.fallback.ast:
                value = expr.evaluate(item.fallback.ast, self.values)
            if value is None:
                return ""
        return _render_numeric(spec, value)

    # -- text helpers -----------------------------------------------------

    def _text_value(self, placed: PlacedText) -> str | None:
        element = placed.element
        if element.literal is not None:
            return element.literal
        if element.value is None:
            return None
        spec = element.format or "{}"
        if element.value.value.type is Type.TIME:
            return _render_time(spec, self.values)
        if element.value.value.type is Type.DATE:
            return _render_date(spec, self.values)
        value = expr.evaluate(element.value.ast, self.values) if element.value.ast else None
        if value is None:
            if element.when_absent == "placeholder":
                return element.placeholder
            if element.when_absent == "fallback" and element.fallback and element.fallback.ast:
                value = expr.evaluate(element.fallback.ast, self.values)
                if value is None:
                    return None
            else:
                return None
        return _render_numeric(spec, value)

    def _blit_bitmap_text(self, font: BakedFont, text: str, placed: PlacedText,
                          color: tuple[int, int, int]) -> None:
        """Draw with the *baked sheet*, so the preview shows the real glyphs."""
        sheet = getattr(font, "sheet_image", None)
        s = self.scale
        width, _ = font.measure(text)
        x, y = placed.anchor_point[0] * s, placed.anchor_point[1] * s
        element = placed.element
        left = {"left": x, "center": x - width * s / 2, "right": x - width * s}[element.align]
        top = y - font.line_height * s / 2 if element.vertical_align == "center" else y

        if sheet is None:
            self._approximate_text(text, placed, color)
            return
        pen = left
        for char in text:
            glyph = font.glyphs.get(char)
            if glyph is None:
                continue
            self._paste_glyph(sheet, glyph, pen, top, color)
            pen += glyph.xadvance * s

    def _paste_glyph(self, sheet: Image.Image, glyph, x: float, y: float,
                     color: tuple[int, int, int]) -> None:
        """Crop one glyph tile off a baked sheet, tint it, and paste it at
        ``(x, y)`` -- the point ``xoffset``/``yoffset`` are measured from, i.e.
        the top-left of the text (or icon)'s own box, already scaled.  Shared
        by text and icons: both are bitmap-font glyphs once baked, and this is
        the one place either gets drawn from a sheet."""
        if not (glyph.width and glyph.height):
            return
        s = self.scale
        tile = sheet.crop((glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height))
        if s != 1:
            tile = tile.resize((glyph.width * s, glyph.height * s), Image.NEAREST)
        tint = Image.new("RGB", tile.size, color)
        position = (int(x + glyph.xoffset * s), int(y + glyph.yoffset * s))
        self.image.paste(tint, position, tile)

    def _approximate_text(self, text: str, placed: PlacedText, color) -> None:
        """Draw system-font text with the same stand-in `wfb.layout` measured.

        The real device faces are not available anywhere (see
        :mod:`wfb.fonts.fallback`), so the glyph shapes here are not the ones the
        watch will draw.  The *position* is exact, and the extent is the same
        estimate the compiler recorded -- because both come from this one face at
        this one size, they cannot disagree.
        """
        s = self.scale
        face = fallback.font_for_height(placed.font_px * s)
        if face is None:
            # No scalable face at all: fall back to marking the extent, which is
            # more honest than drawing text at the wrong size.
            self.draw.rectangle(self._rect(placed.box), outline=(64, 64, 64), width=1)
            return

        x = placed.anchor_point[0] * s
        y = placed.anchor_point[1] * s
        element = placed.element
        anchor_x = {"left": "l", "center": "m", "right": "r"}[element.align]
        anchor_y = "m" if element.vertical_align == "center" else "a"
        self.draw.text((x, y), text, fill=color, font=face, anchor=anchor_x + anchor_y)

    # -- shared -----------------------------------------------------------

    def _rect(self, box) -> list[float]:
        s = self.scale
        return [box.x * s, box.y * s, box.right * s - 1, box.bottom * s - 1]

    def _visible(self, placed) -> bool:
        """`visible:` -- the same rule the device runs, on the sample readings.

        Absent means hidden, so `expr.evaluate` returning ``None`` (which is
        exactly what it does when any input is missing) hides the element,
        matching the generated `if (x == null || !(cond)) return;` rather than
        merely approximating it.  A group's condition is already conjoined into
        every descendant by `wfb.ir`, so nothing here has to walk the tree --
        which is also why the preview cannot silently disagree with the device
        about a subtree.
        """
        expression = placed.element.visible
        if expression is None:
            return True
        if expression.constant is not None:
            return bool(expression.constant)
        if expression.ast is None:
            return True
        return bool(expr.evaluate(expression.ast, self.values))

    def _color(self, expression) -> tuple[int, int, int]:
        if expression is None:
            return (255, 255, 255)
        value = expression.constant
        if value is None and expression.ast is not None:
            value = expr.evaluate(expression.ast, self.values)
        if value is None:
            return (255, 255, 255)
        color = Color.parse(int(value))
        return (color.r, color.g, color.b)


def _synthetic_series(n: int) -> list[float | None]:
    """A deterministic stand-in series, sized to exactly `n` samples.

    Not real data -- there is no `ActivityMonitor`/`Weather` history on the
    host -- but a plausible, varying one, so a graph previews as a shape
    rather than a flat line. A smooth wave rather than noise, so the picture
    is legible and reproducible across runs (no `random`, no seed to manage).

    One sample is deliberately absent (index ``n // 3``, skipped when ``n``
    is too small for a gap to read as intentional) -- "a bucket with no
    samples must not draw" is a real, author-visible behaviour, and a
    preview that always shows a complete series would never demonstrate it.
    """
    if n <= 0:
        return []
    gap = n // 3 if n >= 6 else -1
    return [None if i == gap else 50.0 + 40.0 * math.sin(i * 0.6) for i in range(n)]


def _render_time(spec: str, values: dict) -> str:
    hour = int(values.get("time.hour", 10))
    minute = int(values.get("time.minute", 9))
    second = int(values.get("time.second", 0))
    is24 = bool(values.get("device.is_24_hour", True))
    out = ""
    for part in formatting.parse_time(formatting._strip_braces(spec)):
        if part.code is None:
            out += part.text
        elif part.code == "H":
            out += f"{hour:02d}"
        elif part.code == "I":
            out += f"{(hour % 12) or 12:02d}"
        elif part.code == "l":
            out += f"{(hour % 12) or 12:d}"
        elif part.code == "h":
            out += f"{hour:02d}" if is24 else f"{(hour % 12) or 12:d}"
        elif part.code == "M":
            out += f"{minute:02d}"
        elif part.code == "S":
            out += f"{second:02d}"
        elif part.code == "p":
            out += "AM" if hour < 12 else "PM"
    return out


def _render_date(spec: str, values: dict) -> str:
    out = ""
    for part in formatting.parse_time(formatting._strip_braces(spec), formatting.DATE_CODES):
        if part.code is None:
            out += part.text
        elif part.code == "a":
            out += str(values.get("date.weekday", "Wed"))
        elif part.code == "d":
            out += f"{int(values.get('date.day', 3)):02d}"
        elif part.code == "e":
            out += f"{int(values.get('date.day', 3))}"
        elif part.code == "b":
            out += str(values.get("date.month", "Sep"))
        elif part.code == "m":
            out += f"{int(values.get('date.month_number', 9)):02d}"
        elif part.code == "Y":
            out += f"{int(values.get('date.year', 2026)):04d}"
        elif part.code == "y":
            out += f"{int(values.get('date.year', 2026)) % 100:02d}"
    return out


def _render_numeric(spec: str, value) -> str:
    out = ""
    for part in formatting.parse(spec):
        if isinstance(part, formatting.Literal):
            out += part.text
        else:
            out += _apply_spec(part.spec, value)
    return out


def _apply_spec(spec: str, value) -> str:
    if not spec:
        return str(value)
    try:
        return format(value, spec)
    except (ValueError, TypeError):
        return str(value)


def _quantise_mip64(image: Image.Image) -> Image.Image:
    """Snap to the 64-colour panel, so a dithered colour looks wrong here too."""
    lut = bytes(min(MIP64_LEVELS, key=lambda level: abs(level - value)) for value in range(256))
    return image.point(lut * 3)


def _mask_round(image: Image.Image, scale: int) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, image.width - 1, image.height - 1], fill=255)
    out = Image.new("RGB", image.size, (24, 24, 24))
    out.paste(image, (0, 0), mask)
    return out


def write(resolved: ResolvedFace, path: Path, options: PreviewOptions | None = None) -> Path:
    image = render(resolved, options)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path
