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

from . import catalog, complications, expr, formatting, icons
from .catalog import Type
from .fonts import BakedFont, fallback
from .ir import Progress, Shape, Text
from .layout import (
    COMPLICATION_SLOT_ICON_GAP, PlacedComplicationSlot, PlacedGraph,
    PlacedIcon, PlacedProgress, PlacedShape, PlacedText, ResolvedFace,
)
from .palette import MIP64_LEVELS, Color

#: Illustrative sample values for a `complication_slot` preview, keyed by
#: `wfb.complications.TYPES` name -- not real data (there is no live
#: `Complications` subscription on the host), just something plausible to
#: show instead of an empty box. Falls back to a plain "12"/"--" for any type
#: not listed here.
_COMPLICATION_SLOT_SAMPLE: dict[str, object] = {
    "steps": 8432,
    "heart_rate": 72,
    "calories": 1840,
    "battery": 68,
    "body_battery": 62,
    "floors_climbed": 7,
    "notification_count": 3,
    "stress": 34,
    "current_temperature": 21.0,
    "date": "28 Mar",
    "weekday_monthday": "Wed 28",
    "training_status": "Productive",
}

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

    # `config: colors:` renders at the default scheme's colours, for the same
    # reason -- the preview has no editor to ask either.
    if resolved.face.config_colors is not None:
        default_scheme = resolved.face.color_scheme[resolved.face.config_colors.default]
        for role, color in default_scheme.colors.items():
            values.setdefault(f"config.colors.{role}", color.value)

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
        elif isinstance(placed, PlacedGraph):
            self._graph(placed)
        elif isinstance(placed, PlacedComplicationSlot):
            self._complication_slot(placed)

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

    def _complication_slot(self, placed: PlacedComplicationSlot) -> None:
        """A `complication_slot`, previewed at its slot's *default* choice.

        There is no on-device editor to ask which type the wearer actually
        picked -- the same reason `config:`'s colour axes preview at their
        own `default:` above -- and the default is what a device without the
        native editor (fr955) always shows anyway.  The reading itself is an
        illustrative sample (`_COMPLICATION_SLOT_SAMPLE`), not real data:
        there is no live `Complications` subscription on the host.
        """
        element = placed.element
        slot = self.resolved.face.config_data.get(element.slot)
        if slot is None:
            return
        ctype = complications.TYPES[slot.default]
        color = self._color(element.color)
        s = self.scale

        icon_font = None
        icon_glyph = None
        if placed.icon_font_key is not None:
            icon_name = icons.COMPLICATION_ICON.get(slot.default)
            if icon_name is not None:
                icon_font = self.resolved.fonts.get(placed.icon_font_key)
                icon_glyph = icons.CATALOG[icon_name].codepoint

        text = self._complication_slot_text(element, ctype)
        text_font = (self.resolved.fonts.get(placed.font_reference)
                     if placed.font_is_custom else None)
        if text_font is not None:
            text_width, text_height = text_font.measure(text)
        else:
            text_width, text_height = fallback.measure(text, placed.font_px)

        icon_width = 0.0
        icon_sheet = None
        glyph_obj = None
        icon_height = 0.0
        if icon_font is not None and icon_glyph is not None:
            icon_sheet = getattr(icon_font, "sheet_image", None)
            glyph_obj = icon_font.glyphs.get(icon_glyph)
            if icon_sheet is not None and glyph_obj is not None:
                iw, ih = icon_font.measure(icon_glyph)
                icon_width = iw + COMPLICATION_SLOT_ICON_GAP
                icon_height = ih

        ax, ay = placed.anchor_point
        start_x = ax - (icon_width + text_width) / 2

        if icon_sheet is not None and glyph_obj is not None:
            self._paste_glyph(icon_sheet, glyph_obj, start_x * s,
                              (ay - icon_height / 2) * s, color)

        pen_x = start_x + icon_width
        if text_font is not None:
            sheet = getattr(text_font, "sheet_image", None)
            if sheet is not None:
                top = ay - text_font.line_height / 2
                for char in text:
                    glyph = text_font.glyphs.get(char)
                    if glyph is None:
                        continue
                    self._paste_glyph(sheet, glyph, pen_x * s, top * s, color)
                    pen_x += glyph.xadvance
                return
        face = fallback.font_for_height(placed.font_px * s)
        if face is not None:
            self.draw.text((pen_x * s, ay * s), text, fill=color, font=face, anchor="lm")

    def _complication_slot_text(self, element, ctype) -> str:
        """An illustrative reading for `ctype`, formatted the same way
        `wfb.emit.monkeyc._emit_complication_slot` renders one: an optional
        label prefix, the value, and an optional unit suffix -- approximate,
        since the real label and unit come from the device at runtime."""
        value = _COMPLICATION_SLOT_SAMPLE.get(
            ctype.name, 12 if ctype.value_type != "string" else "--")
        text = ""
        if element.label == "short":
            text += "Now "
        elif element.label == "long":
            text += "Current "
        text += str(value)
        if element.unit and ctype.unit:
            text += f" {ctype.unit}"
        return text

    # -- text helpers -----------------------------------------------------

    def _text_value(self, placed: PlacedText) -> str | None:
        element = placed.element
        if element.literal is not None:
            return element.literal
        if element.value is None:
            return None
        spec = element.format or "{}"
        value_type = element.value.value.type
        if value_type in (Type.TIME, Type.DATE):
            return formatting.render(spec, None, value_type, self.values)
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
        return formatting.render(spec, value, value_type)

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
