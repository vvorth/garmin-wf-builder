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
from dataclasses import dataclass, replace as dataclass_replace
from pathlib import Path

from PIL import Image, ImageDraw

from . import catalog, complications, expr, formatting
from .catalog import Type
from .fonts import BakedFont, fallback
from .ir import Progress, Shape, Text
from .layout import (
    PlacedComplicationSlot, PlacedGraph, PlacedHands, PlacedIcon,
    PlacedPattern, PlacedProgress, PlacedShape, PlacedText, ResolvedFace,
    alignment_shift, complication_slot_pair_geometry, pattern_text_anchor,
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
    "date.day_of_week": "Wed",
    "date.weekday": 4,  # Wednesday: Gregorian.DAY_SUNDAY = 1 .. DAY_SATURDAY = 7
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


class UnknownStyleError(ValueError):
    """`PreviewOptions.style` named something `config: style:` never
    declared, or was given to a design with no `config: style:` at all --
    a clean, listable CLI error rather than a KeyError with no context."""


@dataclass
class PreviewOptions:
    scale: int = 2
    #: Snap every colour to the device's real palette, so a dithered colour
    #: looks wrong in the preview the way it will look wrong on the wrist.
    quantise: bool = True
    #: Render the bezel crop, so an element under it is visibly cut.
    mask_shape: bool = True
    sample: dict[str, object] | None = None
    #: A `config: style:` entry name to render, or `None` for the default
    #: entry.  `wfb preview --style <entry>`.  Raises `UnknownStyleError`
    #: when the design has no `config: style:` at all, or when the name is
    #: not one of its declared entries.
    style: str | None = None
    #: `(hour, minute, second)` to render analog hands at, overriding
    #: `SAMPLE`'s `time.hour`/`time.minute`/`time.second` -- `wfb preview
    #: --time HH:MM[:SS]` (plan 04 §7).  `None` keeps the sample time
    #: (10:09:42), which is also what every non-hands element still reads
    #: through the ordinary `time.hour`/`time.minute`/`time.second` sources.
    time: tuple[int, int, int] | None = None
    #: Render the sleeping `onUpdate` frame instead of the awake one --
    #: `wfb preview --asleep` (plan 04 §7).  Draws the `always_on` element
    #: set when the design has one, the `active` set otherwise, and hides
    #: every `awake`-only second hand either way -- the same choice the
    #: generated view's own `_sleeping` branch makes.
    asleep: bool = False


def _resolve_style_entry(face, name: str | None):
    """The `config: style:` entry `PreviewOptions.style` asks for, or the
    default entry when `name` is `None` -- `None` overall when the design
    has no `config: style:` axis at all (an ordinary, style-less preview).
    """
    axis = face.config_style
    if name is None:
        return axis.default_entry if axis is not None else None
    if axis is None:
        raise UnknownStyleError(
            f"{face.name!r} declares no 'config: style:' at all, so there is "
            f"no entry named {name!r} to render"
        )
    for entry in axis.entries:
        if entry.name == name:
            return entry
    declared = ", ".join(e.name for e in axis.entries)
    raise UnknownStyleError(
        f"{name!r} is not one of this design's config.style entries -- "
        f"declared: {declared}"
    )


def render(resolved: ResolvedFace, options: PreviewOptions | None = None) -> Image.Image:
    options = options or PreviewOptions()
    entry = _resolve_style_entry(resolved.face, options.style)
    values = dict(SAMPLE)
    if options.time is not None:
        # `--time HH:MM[:SS]` -- overrides the sample clock for both hands
        # (which read hour/minute/second directly, with no author
        # expression: §5.5) and any ordinary `time.*`-bound element, so the
        # two agree in one rendered frame.
        hour, minute, second = options.time
        values["time.hour"] = hour
        values["time.minute"] = minute
        values["time.second"] = second
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
    for name, config_entry in resolved.face.config.items():
        values.setdefault(f"config.{name}", config_entry.default.value)

    # `config: style:` renders at the chosen entry's scheme colours (the
    # default entry's, absent `--style`) -- the preview has no editor to ask
    # either.  A layout-only entry has no scheme to seed roles from.
    if entry is not None and entry.colors is not None:
        scheme = resolved.face.color_scheme[entry.colors]
        for role, color in scheme.colors.items():
            values.setdefault(f"config.colors.{role}", color.value)

    device = resolved.device
    scale = max(1, options.scale)
    size = (device.width * scale, device.height * scale)
    image = Image.new("RGB", size, (0, 0, 0))
    draw = ImageDraw.Draw(image)

    # The active layout -- `None` means "no layouts:, or a colour-only
    # entry", in which case every element (`element.layout is None`) draws,
    # exactly like today.  An element that belongs to a *different* layout
    # from the active one is skipped -- the same guard
    # `wfb/emit/monkeyc.py`'s `_emit_layout_guarded_calls` compiles into
    # `if (_configLayout == N)`, run here at preview time instead.
    active_layout = entry.layout if entry is not None else None
    # `--asleep` (plan 04 §7): the sleeping `onUpdate` frame draws the
    # `always_on` element set when the design has one, `active` otherwise --
    # the same choice `wfb/emit/monkeyc.py`'s own `_sleeping` branch makes.
    draw_mode = "always_on" if options.asleep and resolved.in_mode("always_on") else "active"
    renderer = _Renderer(resolved, draw, image, scale, values, options)
    for placed in resolved.items:
        if placed.kind == "group":
            continue
        if draw_mode not in placed.element.modes:
            continue
        if placed.element.layout is not None and placed.element.layout != active_layout:
            continue
        renderer.render_element(placed)

    if options.quantise and device.display_colors == 64:
        image = _quantise_mip64(image)
    if options.mask_shape and device.shape == "round":
        image = _mask_round(image, scale)
    return image


def render_all_styles(resolved: ResolvedFace, options: PreviewOptions | None = None) -> Image.Image:
    """Every `config: style:` entry, rendered and laid out side by side in
    one image -- `wfb preview --all-styles`.

    Same renderer, run once per entry (:func:`render`, through
    `PreviewOptions.style`): there is no second rendering path for this to
    drift from (ADR 0004).  Each panel gets a caption bar naming the
    entry's own label (`Face.style_label`, the same fallback the generated
    `<style label=...>` resource uses), so the two never disagree about
    what an entry is called either.

    Raises `UnknownStyleError` the same way `render` does when the design
    declares no `config: style:` at all -- there is nothing to lay out side
    by side.
    """
    options = options or PreviewOptions()
    face = resolved.face
    axis = face.config_style
    if axis is None:
        raise UnknownStyleError(
            f"{face.name!r} declares no 'config: style:' at all, so there is "
            "nothing for --all-styles to lay out"
        )
    caption_height = max(16, 10 * max(1, options.scale))
    panels = []
    for entry in axis.entries:
        panel = render(resolved, dataclass_replace(options, style=entry.name))
        label = face.style_label(entry) or entry.name
        panels.append((panel, label))

    gap = max(1, options.scale)
    total_width = sum(p.width for p, _ in panels) + gap * (len(panels) - 1)
    total_height = max(p.height for p, _ in panels) + caption_height
    composed = Image.new("RGB", (total_width, total_height), (16, 16, 16))
    draw = ImageDraw.Draw(composed)
    face_font = fallback.font_for_height(caption_height - 4)
    x = 0
    for panel, label in panels:
        composed.paste(panel, (x, caption_height))
        if face_font is not None:
            draw.text((x + panel.width / 2, caption_height / 2), label,
                      fill=(220, 220, 220), font=face_font, anchor="mm")
        x += panel.width + gap
    return composed


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
        elif isinstance(placed, PlacedHands):
            self._hands(placed)
        elif isinstance(placed, PlacedPattern):
            self._pattern(placed)

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
            # Same whole-degree rule the generated code gets from
            # WfbArc.drawSpan -- see `arc_span`.
            cx, cy = placed.center[0] * s, placed.center[1] * s
            r = placed.radius * s
            span = arc_span(placed.start_angle, placed.sweep)
            if r > 0 and span is not None:
                self.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
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

    def _hands(self, placed: PlacedHands) -> None:
        """`type: hands` -- the same three angle formulas
        `runtime-lib/WfbHands.mc` computes on the device (plan 04 §5.5),
        applied here to the *resolved* geometry so this can never disagree
        with the generated code about a hand's shape or its axis.

        `--asleep` hides an `awake`-only second hand, the same choice the
        generated `if (!_sleeping)` branch makes; a `seconds: never` hand
        was already excluded at resolve time (`Resolver._resolve_hands`),
        so there is nothing here to skip for it.
        """
        element = placed.element
        s = self.scale
        cx, cy = placed.center[0] * s, placed.center[1] * s
        hour = int(self.values.get("time.hour", 0) or 0)
        minute = int(self.values.get("time.minute", 0) or 0)
        second = int(self.values.get("time.second", 0) or 0)
        angles = {
            "hour": math.radians(((hour % 12) * 60 + minute) * 0.5),
            "minute": math.radians(minute * 6.0),
            "second": math.radians(second * 6.0),
        }
        for hand_name in ("hour", "minute", "second"):
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            if hand_name == "second" and element.seconds == "awake" and self.options.asleep:
                continue
            sin_t, cos_t = math.sin(angles[hand_name]), math.cos(angles[hand_name])
            for part in hand.parts:
                self._hand_part(part, cx, cy, s, sin_t, cos_t)

    def _hand_part(self, part, cx: float, cy: float, s: int,
                   sin_t: float, cos_t: float, values: dict | None = None) -> None:
        fill = self._color(part.color, values)

        def rotated(x: float, y: float) -> tuple[float, float]:
            return (cx + (x * cos_t - y * sin_t) * s, cy + (x * sin_t + y * cos_t) * s)

        if part.shape == "polygon":
            if len(part.points) >= 3:
                self.draw.polygon([rotated(x, y) for x, y in part.points], fill=fill)
        elif part.shape == "line":
            x1, y1 = rotated(part.x1, part.y1)
            x2, y2 = rotated(part.x2, part.y2)
            self.draw.line([x1, y1, x2, y2], fill=fill, width=max(1, part.thickness * s))
        else:  # circle
            x, y = rotated(part.x, part.y)
            r = part.radius * s
            box = [x - r, y - r, x + r, y + r]
            if part.filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, part.thickness * s))

    def _pattern(self, placed: PlacedPattern) -> None:
        """`type: pattern` -- one template, drawn once per copy through
        :meth:`PlacedPattern.transform` (plan 05 §5.3/§6.2): the very same
        `(ox, oy, sin, cos)` the generated draw method computes on the
        device, so this preview and codegen cannot disagree about where a
        copy lands. Copies draw ascending, parts in list order within a
        copy (§5.3) -- the same nested-loop order the generated code uses.
        A polygon/line/circle part reuses `_hand_part` (a pattern part is
        authored exactly like a hand part, §5.2); an `arc` part has no
        rotate-the-vertices equivalent -- its *start angle* turns with the
        copy instead (`_pattern_arc`); a `text` part draws upright glyphs
        at the copy's own rounded anchor instead of rotating vertices
        (`_pattern_text`, plan 06 §3.4).

        `when_absent: hide` (B7, 2026-09-15): the device reads every
        nullable source a pattern's colours/part `visible:`s use once, before
        its loop, and returns early if any is null -- mirrored here by
        `_pattern_absent`, checked once for the whole element, not per copy
        (the reading is a fact about the frame, not about one copy). Per
        copy, each part's own `visible:` (B) is evaluated with the same
        `copy`-bound `values` its colour uses; false/`None` skips only that
        part, for that copy.
        """
        element = placed.element
        if self._pattern_absent(element):
            return
        s = self.scale
        for index in placed.copies:
            ox, oy, sin_t, cos_t = placed.transform(index)
            cx, cy = ox * s, oy * s
            # `copy` is the generated loop's `i`: a colour reading it is
            # evaluated afresh for every copy, exactly as the device does.
            values = {**self.values, expr.COPY: index}
            for part_index, part in enumerate(placed.parts):
                visible = element.parts[part_index].visible
                if visible is not None and not self._pattern_part_visible(visible, values):
                    continue
                if part.shape == "arc":
                    self._pattern_arc(part, ox, oy, index, placed, s, values)
                elif part.shape == "text":
                    self._pattern_text(part, ox, oy, sin_t, cos_t, index, values)
                else:
                    self._hand_part(part, cx, cy, s, sin_t, cos_t, values)

    def _pattern_absent(self, element) -> bool:
        """Whether any nullable source this pattern's colours (`element.colors`,
        already the element default plus every part's override, deduplicated)
        or any part's own `visible:` reads is absent in the current sample
        (`self.values` -- `SAMPLE` plus any `--sample`/`options.sample`
        overrides) -- the host-side mirror of the null guard the device
        emits before its own loop (`wfb.emit.monkeyc._emit_pattern`'s
        `plan.guards(placed)`, fed by the same colours and part `visible:`s
        via `PatternElement._own_expressions`).  A build that reached this
        renderer already guarantees `when_absent: hide` is set whenever this
        can be `True` (`Builder._check_pattern_absence`) -- checked on the
        sources themselves, not the flag, so this cannot drift from the
        guard the device actually runs.  The element's own `visible:` is
        deliberately not consulted here -- that is a different, already-
        handled axis (`_visible`), covering the whole element regardless of
        `when_absent:`.
        """
        sources: set[str] = set()
        for expression in element.colors:
            sources.update(expression.sources)
        for part in element.parts:
            if part.visible is not None:
                sources.update(part.visible.sources)
        return any(
            catalog.CATALOG[path].guard_needed and self.values.get(path) is None
            for path in sources
        )

    def _pattern_part_visible(self, expression, values: dict) -> bool:
        if expression.constant is not None:
            return bool(expression.constant)
        if expression.ast is None:
            return True
        return bool(expr.evaluate(expression.ast, values))

    def _pattern_arc(self, part, ox: float, oy: float, index: int,
                     placed: PlacedPattern, s: int, values: dict) -> None:
        """An `arc` template part -- always centred on the copy's own
        origin (plan 05 D3, `at:` is rejected on it), so there are no
        vertices to rotate: only its *start angle* turns with the copy,
        exactly as `WfbArc.drawSpan` is called on the device (plan 05
        §6.4): `part.start_angle + start + index * step`, which collapses
        to plain `part.start_angle` for a linear pattern (`placed.start`/
        `placed.step` are both `0` there, D3/§5.3). Drawn through the same
        whole-degree `arc_span` rule a `shape: arc` element uses.
        """
        fill = self._color(part.color, values)
        cx, cy = ox * s, oy * s
        r = part.radius * s
        author_start = part.start_angle + placed.start + index * placed.step
        span = arc_span(author_start, part.sweep)
        if r > 0 and span is not None:
            self.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
                          fill=fill, width=max(1, part.thickness * s))

    def _pattern_text(self, part, ox: float, oy: float, sin_t: float, cos_t: float,
                      index: int, values: dict) -> None:
        """A `shape: text` template part (plan 06 §3.4): upright glyphs at
        this copy's own anchor, rounded the same half-up way
        `runtime-lib/WfbGeom.mc`'s `drawTextRotated` rounds it on the
        device (:func:`pattern_text_anchor`) -- the anchor *turns* (radial)
        or *steps* (linear) with the copy, but the glyphs themselves never
        rotate, exactly as `_hand_part`'s vertex rotation does not apply to
        them (plan 05 §5.2's "upright text is not rotation-invariant").
        Draws through the very same `_draw_text` a `text` element uses
        (`_text`), so a pattern's numerals and a standalone `text` element
        can never disagree about how a font/align/vertical_align combination
        looks.
        """
        text = part.texts[index]
        color = self._color(part.color, values)
        anchor = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
        font: BakedFont | None = (
            self.resolved.fonts.get(part.font_reference) if part.font_is_custom else None
        )
        self._draw_text(font, text, anchor, part.align, part.vertical_align, part.font_px, color)

    def _text(self, placed: PlacedText) -> None:
        element = placed.element
        text = self._text_value(placed)
        if text is None:
            return
        color = self._color(element.color)
        font: BakedFont | None = (
            self.resolved.fonts.get(placed.font_reference) if placed.font_is_custom else None
        )
        self._draw_text(font, text, placed.anchor_point, element.align, element.vertical_align,
                        placed.font_px, color, box=placed.box)

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
            # The whole-degree rule WfbArc.drawSpan applies on the device --
            # see `arc_span`.
            track = arc_span(placed.start_angle, placed.sweep)
            if element.track_color is not None and track is not None:
                self.draw.arc(box, *track, fill=self._color(element.track_color), width=width)
            fill = arc_span(placed.start_angle, placed.sweep * fraction) if fraction > 0 else None
            if fill is not None:
                self.draw.arc(box, *fill, fill=self._color(element.color), width=width)
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
        icon_color = self._color(element.icon_color) if element.icon_color is not None else color
        s = self.scale

        icon_font = None
        icon_glyph = None
        if placed.icon_font_key is not None:
            icon = slot.icons.get(slot.default)
            if icon is not None:
                icon_font = self.resolved.fonts.get(placed.icon_font_key)
                icon_glyph = icon.codepoint

        text = self._complication_slot_text(element, ctype)
        text_font = (self.resolved.fonts.get(placed.font_reference)
                     if placed.font_is_custom else None)
        if text_font is not None:
            text_width, text_height = text_font.measure(text)
        else:
            # `fallback.measure`'s second return is whether real metrics were
            # used, not a height -- `wfb.layout.Resolver._resolve_complication_
            # slot` uses the declared font size itself as the line-height
            # estimate for exactly this case, and this mirrors it.
            text_width, _ = fallback.measure(text, placed.font_px)
            text_height = placed.font_px

        icon_width = 0
        icon_height = 0
        icon_sheet = None
        glyph_obj = None
        if icon_font is not None and icon_glyph is not None:
            icon_sheet = getattr(icon_font, "sheet_image", None)
            glyph_obj = icon_font.glyphs.get(icon_glyph)
            if icon_sheet is not None and glyph_obj is not None:
                icon_width, icon_height = icon_font.measure(icon_glyph)
            else:
                icon_sheet = None
                glyph_obj = None

        # One shared geometry function for every position (plan 03 §6.3) --
        # `wfb.layout.complication_slot_pair_geometry`, the same one
        # `Resolver._resolve_complication_slot` uses to size the estimated
        # box, called here with the *actual* measured extents this preview
        # already has (unlike layout, which only has an estimate).
        geometry = complication_slot_pair_geometry(
            placed.icon_position, icon_width, icon_height, text_width, text_height,
            placed.icon_gap_px,
        )
        ax, ay = placed.anchor_point
        origin_x = ax - geometry.width / 2
        origin_y = ay - geometry.height / 2

        if icon_sheet is not None and glyph_obj is not None:
            self._paste_glyph(icon_sheet, glyph_obj,
                              (origin_x + geometry.icon_x) * s,
                              (origin_y + geometry.icon_y) * s, icon_color)

        pen_x = origin_x + geometry.text_x
        top = origin_y + geometry.text_y
        if text_font is not None:
            sheet = getattr(text_font, "sheet_image", None)
            if sheet is not None:
                for char in text:
                    glyph = text_font.glyphs.get(char)
                    if glyph is None:
                        continue
                    self._paste_glyph(sheet, glyph, pen_x * s, top * s, color)
                    pen_x += glyph.xadvance
                return
        face = fallback.font_for_height(placed.font_px * s)
        if face is not None:
            self.draw.text((pen_x * s, top * s), text, fill=color, font=face, anchor="la")

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
        text += complications.format_value(value)
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

    def _draw_text(self, font: BakedFont | None, text: str, anchor: tuple[int, int],
                   align: str, vertical_align: str, font_px: int,
                   color: tuple[int, int, int], box=None) -> None:
        """Draw `text` upright at `anchor`, exactly as a `text` element and a
        pattern `shape: text` part both want (plan 06 §3.4 B3): through the
        baked sheet when `font` is a custom one, the Pillow stand-in
        otherwise. The one place either kind of element actually puts ink
        down, so `_text` and `_pattern_text` cannot drift apart. `box`, an
        `IntBox` or `None`, is only ever used by the rare "no scalable
        system face at all" fallback in `_approximate_text` -- a `text`
        element has one (its own resolved box) to outline instead of
        drawing nothing; a pattern text part has none to give, so it simply
        draws nothing in that (untested, essentially unreachable) case.
        """
        if font is not None:
            self._blit_bitmap_text(font, text, anchor, align, vertical_align, font_px, color, box)
        else:
            self._approximate_text(text, anchor, align, vertical_align, font_px, color, box)

    def _blit_bitmap_text(self, font: BakedFont, text: str, anchor: tuple[int, int],
                          align: str, vertical_align: str, font_px: int,
                          color: tuple[int, int, int], box=None) -> None:
        """Draw with the *baked sheet*, so the preview shows the real glyphs."""
        sheet = getattr(font, "sheet_image", None)
        s = self.scale
        width, _ = font.measure(text)
        x, y = anchor[0] * s, anchor[1] * s
        line_height = font.line_height * s
        # The one shared placement rule (`wfb.layout.alignment_shift`), not a
        # private dict literal (R8) -- `bottom` (renamed from `baseline`,
        # R6) now puts the ink's bottom edge on `y`, fixing the §1.2 bug
        # here instead of drawing it hanging down from `y` like `top` did.
        dx, dy = alignment_shift(width * s, line_height, align, vertical_align)
        left = x + dx - width * s / 2
        top = y + dy - line_height / 2

        if sheet is None:
            self._approximate_text(text, anchor, align, vertical_align, font_px, color, box)
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

    def _approximate_text(self, text: str, anchor: tuple[int, int], align: str,
                          vertical_align: str, font_px: int, color, box=None) -> None:
        """Draw system-font text with the same stand-in `wfb.layout` measured.

        The real device faces are not available anywhere (see
        :mod:`wfb.fonts.fallback`), so the glyph shapes here are not the ones the
        watch will draw.  The *position* is exact, and the extent is the same
        estimate the compiler recorded -- because both come from this one face at
        this one size, they cannot disagree.

        `align`/`vertical_align` are handed straight to Pillow's own
        multi-character text anchor (`ImageDraw.text`'s `anchor=`) rather
        than reimplemented as a left/center/right offset here (R8) -- Pillow
        already knows how to place text by its left/middle/right edge and by
        its ascender/middle/descender line, so there is nothing of
        `wfb.layout.alignment_shift`'s own rule to duplicate; this is a
        one-to-one translation into Pillow's vocabulary, not a second copy
        of the placement math. `bottom` (renamed from `baseline`, R6) maps
        to Pillow's descender anchor `"d"`, fixing the §1.2 bug here too:
        `top` and the old `baseline` used to collapse onto the same `"a"`
        anchor, so a bottom-aligned line drew hanging down from the point
        exactly like a top-aligned one.
        """
        s = self.scale
        face = fallback.font_for_height(font_px * s)
        if face is None:
            # No scalable face at all: fall back to marking the extent, which is
            # more honest than drawing text at the wrong size -- only possible
            # for a `text` element, which has a `box` to outline; a pattern
            # text part (`box is None`) simply draws nothing here.
            if box is not None:
                self.draw.rectangle(self._rect(box), outline=(64, 64, 64), width=1)
            return

        x = anchor[0] * s
        y = anchor[1] * s
        # "left"/"right" share Pillow's own first letter; anything else
        # (only "center" is a valid value here) is the middle anchor.
        anchor_x = align[0] if align in ("left", "right") else "m"
        if vertical_align == "top":
            anchor_y = "a"
        elif vertical_align == "bottom":
            anchor_y = "d"
        else:
            anchor_y = "m"
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

    def _color(self, expression, values: dict | None = None) -> tuple[int, int, int]:
        """`values` overrides `self.values` -- a pattern passes its own, with
        `copy` bound to the copy being drawn."""
        if expression is None:
            return (255, 255, 255)
        value = expression.constant
        if value is None and expression.ast is not None:
            value = expr.evaluate(expression.ast, self.values if values is None else values)
        if value is None:
            return (255, 255, 255)
        color = Color.parse(int(value))
        return (color.r, color.g, color.b)


def _round_away(degrees: float) -> int:
    """Round half away from zero -- `WfbArc.roundAway`, not Python's banker's `round`."""
    return int(degrees - 0.5) if degrees < 0 else int(degrees + 0.5)


def arc_span(start_angle: float, sweep: float) -> tuple[int, int] | None:
    """The Pillow ``(start, end)`` for an arc, or None when nothing is drawn.

    The host twin of `runtime-lib/WfbArc.mc`'s `drawSpan`. `Dc.drawArc` only
    takes whole degrees and draws a complete circle when start equals end, so
    the device decides on the *rounded* sweep: under half a degree draws
    nothing, and only a sweep of 360 or more is the full ring. The preview
    applies the same rule so it cannot show a sliver the watch will not draw.
    ``start_angle`` is the author's clockwise-from-12 angle; Pillow runs
    clockwise from 3 o'clock, hence the 90-degree shift, and the endpoints are
    ordered so Pillow takes the short way round.
    """
    whole = max(-360, min(360, _round_away(sweep)))
    if whole == 0:
        return None
    start = _round_away(start_angle) - 90
    end = start + whole
    return (start, end) if whole > 0 else (end, start)


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


def write_all_styles(resolved: ResolvedFace, path: Path,
                     options: PreviewOptions | None = None) -> Path:
    image = render_all_styles(resolved, options)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path
