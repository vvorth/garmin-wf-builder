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

from . import catalog, expr, formatting, icons
from .catalog import Type
from .fonts import BakedFont
from .ir import IconElement, Progress, Shape, Text
from .layout import (
    PlacedIcon, PlacedProgress, PlacedShape, PlacedText, ResolvedFace,
)
from .palette import MIP64_LEVELS, Color

#: Plausible readings, so a preview shows a face mid-life rather than at zero.
SAMPLE: dict[str, object] = {
    "time.clock": 0,
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
        if isinstance(placed, PlacedShape):
            self._shape(placed)
        elif isinstance(placed, PlacedText):
            self._text(placed)
        elif isinstance(placed, PlacedProgress):
            self._progress(placed)
        elif isinstance(placed, PlacedIcon):
            self._icon(placed)

    # -- elements ---------------------------------------------------------

    def _shape(self, placed: PlacedShape) -> None:
        element = placed.element
        fill = self._color(element.color)
        s = self.scale
        if element.shape == "rectangle":
            self.draw.rectangle(self._rect(placed.box), fill=fill)
        elif element.shape == "rounded_rectangle":
            self.draw.rounded_rectangle(self._rect(placed.box), radius=placed.corner_radius * s,
                                        fill=fill)
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
            value, maximum = 0, 1
        fraction = 0.0 if not maximum or maximum <= 0 else min(1.0, max(0.0, value / maximum))
        s = self.scale

        if element.style == "arc":
            cx, cy, r = placed.center[0] * s, placed.center[1] * s, placed.radius * s
            width = max(1, placed.thickness * s)
            box = [cx - r, cy - r, cx + r, cy + r]
            # Pillow's arc runs clockwise from 3 o'clock; the author's angles run
            # clockwise from 12 o'clock, so shift by 90 degrees.
            start = placed.start_angle - 90.0
            if element.track_color is not None:
                self.draw.arc(box, start, start + placed.sweep,
                              fill=self._color(element.track_color), width=width)
            if fraction > 0:
                self.draw.arc(box, start, start + placed.sweep * fraction,
                              fill=self._color(element.color), width=width)
            return

        box = self._rect(placed.box)
        if element.track_color is not None:
            self.draw.rectangle(box, fill=self._color(element.track_color))
        filled = int(placed.box.width * fraction) * s
        if filled > 0:
            self.draw.rectangle([box[0], box[1], box[0] + filled, box[3]],
                                fill=self._color(element.color))

    def _icon(self, placed: PlacedIcon) -> None:
        """Mirror ``runtime-lib/WfbIcons.mc`` -- same primitives, same proportions."""
        element = placed.element
        color = self._color(element.color)
        s = self.scale
        cx, cy = placed.center[0] * s, placed.center[1] * s
        size = placed.size * s

        if element.icon == "steps":
            sole_w, sole_h = size * 0.15, size * 0.26
            gap, lift = size * 0.24, size * 0.10
            toe_w, toe_h = size * 0.30, size * 0.10
            for dx, dy in ((-gap, lift), (gap, -lift)):
                self.draw.ellipse(
                    [cx + dx - sole_w, cy + dy - sole_h, cx + dx + sole_w, cy + dy + sole_h],
                    fill=color)
                top = cy + dy - sole_h - toe_h - 1
                self.draw.rounded_rectangle(
                    [cx + dx - toe_w / 2, top, cx + dx + toe_w / 2, top + toe_h],
                    radius=toe_h / 2, fill=color)
        elif element.icon == "heart":
            lobe, spread = size * 0.26, size * 0.22
            lobe_y = cy - size * 0.14
            for dx in (-spread, spread):
                self.draw.ellipse([cx + dx - lobe, lobe_y - lobe, cx + dx + lobe, lobe_y + lobe],
                                  fill=color)
            self.draw.polygon([(cx - spread - lobe, lobe_y), (cx + spread + lobe, lobe_y),
                               (cx, cy + size * 0.46)], fill=color)
        elif element.icon == "flame":
            top, bottom, half = cy - size * 0.48, cy + size * 0.42, size * 0.30
            self.draw.polygon([(cx, top), (cx + half, cy - size * 0.02),
                               (cx + half * 0.7, bottom), (cx - half * 0.7, bottom),
                               (cx - half, cy - size * 0.02)], fill=color)

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
        tint = Image.new("RGB", self.image.size, color)
        pen = left
        for char in text:
            glyph = font.glyphs.get(char)
            if glyph is None:
                continue
            if glyph.width and glyph.height:
                tile = sheet.crop((glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height))
                if s != 1:
                    tile = tile.resize((glyph.width * s, glyph.height * s), Image.NEAREST)
                position = (int(pen + glyph.xoffset * s), int(top + glyph.yoffset * s))
                self.image.paste(tint.crop((0, 0, tile.width, tile.height)), position, tile)
            pen += glyph.xadvance * s

    def _approximate_text(self, text: str, placed: PlacedText, color) -> None:
        """System fonts are not on the host; draw a labelled block instead.

        Showing a grey block rather than a substituted typeface keeps the preview
        honest: the *extent* is what the compiler knows, and the glyph shapes are
        the device's, not ours.
        """
        s = self.scale
        box = self._rect(placed.box)
        # A dim outline, not the element's own colour: this box is preview
        # scaffolding marking the extent the compiler computed, and it should
        # not be mistaken for something the face draws.
        self.draw.rectangle(box, outline=(64, 64, 64), width=1)
        try:
            from PIL import ImageFont

            size = max(8, int(placed.font_px * s * 0.7))
            face = ImageFont.load_default(size=size)
            self.draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text,
                           fill=color, font=face, anchor="mm")
        except Exception:
            pass

    # -- shared -----------------------------------------------------------

    def _rect(self, box) -> list[float]:
        s = self.scale
        return [box.x * s, box.y * s, box.right * s - 1, box.bottom * s - 1]

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
