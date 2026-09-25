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

**Typeface, not just position, can silently drift too**: a system or
vector font resolves through `wfb.fonts.fallback.system_face`, which prefers
the user's own Garmin font root but falls back to a free stand-in, or even
Pillow's bundled default, with no error -- the geometry still agrees with
the device, but the glyph *shapes* do not. `render`'s `used_faces` parameter
is how a caller finds out (`stand_in_warning`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace as dataclass_replace
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from . import aod_mask, catalog, complications, expr, formatting, kinds
from .catalog import Type
from .devices import FontMetric
from .fonts import BakedFont, fallback
from .fonts import cft as cft_fonts
from .ir import aod_color_choice, disc_perimeter_offsets
from .layout import (
    HAND_ANGLES, PatternTextAngle, PlacedComplicationSlot, PlacedGraph, PlacedHands,
    PlacedPattern, PlacedShape, PlacedText, ResolvedFace,
    alignment_shift, complication_slot_pair_geometry, pattern_text_anchor,
    radial_align_offset, radial_direction_sign,
)
from .palette import MIP64_LEVELS, Color, dim_fraction

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
    #: --time HH:MM[:SS]`.  `None` keeps the sample time (10:09:42), which
    #: is also what every non-hands element still reads through the
    #: ordinary `time.hour`/`time.minute`/`time.second` sources.
    time: tuple[int, int, int] | None = None
    #: Hide every `awake`-only second hand -- `wfb preview --asleep`, the
    #: same choice the generated view makes while `_sleeping`. `aod` below
    #: implies this too, since AOD only ever runs while asleep.
    asleep: bool = False
    #: Render the AMOLED always-on-display frame instead of the awake one --
    #: `wfb preview --aod`. Draws the resolved `aod:` set (`Element.aod is
    #: not None`), restyled and dimmed exactly as codegen does
    #: (`_Renderer._aod_field`/`_aod_color`). A design with no `aod:`
    #: anywhere renders blank under the face default (`hide`).
    aod: bool = False
    #: `--fonts DIR` -- overrides `wfb.fonts.fetch_system.garmin_font_root`'s
    #: search, the same override `wfb doctor --fonts` takes; threaded through
    #: every `fallback.system_face` call this renderer makes.
    fonts_root: str | None = None
    #: Apply the face's own `aod: {mask: ...}` when rendering `--aod`, at the
    #: frame's own minute, so a preview shows exactly what the device will.
    #: `check_aod_burn_in` sets this `False` to render the frame once,
    #: unmasked, and apply each of the four phases itself (worst-of-four).
    aod_mask: bool = True


#: `SystemFace.match` levels a stand-in warning is owed (plan 12 R1.3):
#: `"garmin"` and `"exact"`/`"family"` all draw the *same letterforms* the
#: device does -- the installed root, or a free release of the very same
#: (or, for `family`, a closely related) typeface -- so only `"substitute"`
#: (a different family entirely, picked for a similar role) and `"none"`
#: (Pillow's own bundled default, `wfb.fonts.fallback._pillow_fallback`)
#: change the glyph shapes a preview actually draws.
_STAND_IN_MATCHES = frozenset({"substitute", "none"})

#: How much larger `_paste_rotated_run` renders its throwaway layer before
#: rotating, so the rotation samples a raster fine enough to approximate
#: Garmin's own rotated-*outline* rasterisation instead of `Image.rotate`
#: blurring an already-aliased bitmap. 4x was visually indistinguishable
#: from 8x (sharp stems, no ringing) while 2x still showed soft edges, at
#: well under a millisecond per run.
_ROTATED_TEXT_SUPERSAMPLE = 4


def _drawn_with(face: "fallback.SystemFace") -> str:
    """What a stand-in warning names as "drawn instead": the located file's
    own basename, or `"Pillow default"` for a `"none"` match, which has no
    file at all (`SystemFace.path is None`)."""
    return Path(face.path).name if face.path else "Pillow default"


def stand_in_warning(used_faces: dict[FontMetric, "fallback.SystemFace"]) -> str | None:
    """One warning block naming every face `used_faces` recorded at match
    level `"substitute"`/`"none"`, or `None` when there are none (always,
    with the Garmin font root installed).

    `wfb.cli._render_preview` passes one dict to every render of a run and
    calls this once at the end, so the warning fires once per *run*, not
    per device or panel. Rows are sorted for a rerun-stable order, and
    collapsed to one per substituted *typeface* `(name, file, match)`: the
    metrics are keyed per symbol and size, so one font at two sizes or on
    two devices would otherwise count twice.
    """
    affected = sorted(
        {
            (metric.face or metric.symbol, _drawn_with(face), face.match)
            for metric, face in used_faces.items()
            if face.match in _STAND_IN_MATCHES
        }
    )
    if not affected:
        return None

    name_width = max(len(name) for name, _, _ in affected)
    drawn_width = max(len(drawn) for _, drawn, _ in affected)
    count = len(affected)
    lines = [
        f"warning: {count} font{'s' if count != 1 else ''} "
        f"{'were' if count != 1 else 'was'} drawn with a stand-in, not "
        "Garmin's own face --",
        "         glyph shapes will not match the simulator:",
    ]
    for name, drawn, match in affected:
        lines.append(f"           {name:<{name_width}}  -> {drawn:<{drawn_width}}  ({match})")
    lines.append("         install the SDK Manager's Fonts directory at vendor/fonts/,")
    lines.append("         or set WFB_FONTS / pass --fonts DIR -- see `wfb doctor`.")
    return "\n".join(lines)


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


def render(resolved: ResolvedFace, options: PreviewOptions | None = None, *,
          used_faces: dict[FontMetric, "fallback.SystemFace"] | None = None) -> Image.Image:
    """Render `resolved` to an `Image`.

    `used_faces`, when given, is a caller-owned dict this render **adds
    into**: every distinct `FontMetric` it resolved a `fallback.SystemFace`
    for. A caller wanting one report for a whole run (`wfb.cli.
    _render_preview`) passes the same dict to every call and reads it once
    at the end (`stand_in_warning`), which keeps this module free of global
    state.
    """
    options = options or PreviewOptions()
    entry = _resolve_style_entry(resolved.face, options.style)
    values = dict(SAMPLE)
    if options.time is not None:
        # `--time HH:MM[:SS]` -- overrides the sample clock for both hands
        # (which read hour/minute/second directly, with no author
        # expression) and any ordinary `time.*`-bound element, so the
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

    # The active layout (`None`: no `layouts:`, or a colour-only entry). An
    # element of a *different* layout is skipped -- the guard
    # `wfb.emit.monkeyc.view._emit_layout_guarded` compiles into
    # `if (_configLayout == N)`.
    active_layout = entry.layout if entry is not None else None
    renderer = _Renderer(resolved, draw, image, scale, values, options, used_faces)
    for placed in resolved.items:
        if placed.kind == "group":
            continue
        if options.aod:
            # `--aod`: the resolved `aod:` set, exactly what
            # `wfb.emit.monkeyc.view._emit_aod_body` draws.
            if placed.element.aod is None:
                continue
        elif "active" not in placed.element.modes:
            continue
        if placed.element.layout is not None and placed.element.layout != active_layout:
            continue
        renderer.render_element(placed)

    if options.aod and resolved.face.aod_mask and options.aod_mask:
        # The same moving 2x2 mask the device applies, at the frame's own
        # minute. Before quantising/cropping: black is already an exact MIP
        # colour, but masking after would let an anti-aliased bezel fringe
        # leak back in as non-black.
        image = aod_mask.apply(image, int(values["time.minute"]), scale)

    if options.quantise and device.display_colors == 64:
        image = _quantise_mip64(image)
    if options.mask_shape and device.shape == "round":
        image = _mask_round(image, scale)
    return image


def render_all_styles(resolved: ResolvedFace, options: PreviewOptions | None = None, *,
                      used_faces: dict[FontMetric, "fallback.SystemFace"] | None = None) -> Image.Image:
    """Every `config: style:` entry, rendered and laid out side by side in
    one image -- `wfb preview --all-styles`.

    Same renderer, run once per entry (:func:`render`, through
    `PreviewOptions.style`): there is no second rendering path for this to
    drift from (ADR 0004).  Each panel gets a caption bar naming the
    entry's own label (`Face.style_label`, the same fallback the generated
    `<style label=...>` resource uses), so the two never disagree about
    what an entry is called either.

    `used_faces` is passed through to every panel's `render` call.

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
        panel = render(resolved, dataclass_replace(options, style=entry.name), used_faces=used_faces)
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


#: Minutes in a day -- the range `--minute` accepts and the number of frames
#: `render_aod_heatmap` sums by default.
MINUTES_PER_DAY = 24 * 60


def render_aod_heatmap(resolved: ResolvedFace, options: PreviewOptions | None = None, *,
                       minutes: Iterable[int] | None = None,
                       used_faces: dict[FontMetric, "fallback.SystemFace"] | None = None,
                       ) -> tuple[Image.Image, float]:
    """Sum the AOD frame over every minute of the day into one normalised
    image -- `wfb preview --aod --heatmap`, a stand-in for the simulator's
    own Screen Heat Map (research 11 §1.5), which is unreachable here (root
    `CLAUDE.md` §3).

    Renders the AOD frame once per minute in ``minutes``
    (`range(MINUTES_PER_DAY)` by default; a test can pass a handful) and
    counts, per pixel, how many minutes left it lit -- any colour other than
    pure black, the definition `wfb.lint.check_aod_burn_in` uses too. The
    image is that count scaled so a pixel lit every minute is white; the
    `float` is the peak count as a fraction of the minutes rendered.

    This answers how *persistently* a pixel lights over a day -- closer to
    the 3-minute rule -- not how *much* of the screen is lit, which is the
    burn-in lint's question; neither substitutes for the other.

    The accumulator is Pillow's 32-bit `"I"` mode because an 8-bit add
    clips at 255, which an always-lit pixel reaches almost immediately.
    """
    from PIL import ImageMath

    options = options or PreviewOptions()
    base = dataclass_replace(options, aod=True, mask_shape=False)
    device = resolved.device
    scale = max(1, base.scale)
    minute_list = list(range(MINUTES_PER_DAY) if minutes is None else minutes)
    accum = Image.new("I", (device.width * scale, device.height * scale), 0)
    for minute in minute_list:
        frame = render(resolved, dataclass_replace(base, time=(minute // 60, minute % 60, 0)),
                       used_faces=used_faces)
        r, g, b = frame.split()
        lit = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 1 if v else 0)
        accum = ImageMath.lambda_eval(lambda args: args["a"] + args["b"],
                                      a=accum, b=lit.convert("I"))
    count = max(len(minute_list), 1)
    heat = accum.point(lambda v: v * (255.0 / count)).convert("L").convert("RGB")
    if options.mask_shape and device.shape == "round":
        heat = _mask_round(heat, scale)
    return heat, accum.getextrema()[1] / count


@lru_cache(maxsize=4096)
def _bitmap_glyph_mask(path: str, char: str, scale: int) -> Image.Image:
    """`char`'s `.cft` glyph cell as an `"L"` ink mask (`level * 255 //
    max_level`), upscaled `scale`x with `Image.NEAREST` -- what
    `_Renderer._draw_bitmap_line` pastes a colour through, since a bitmap
    `SystemFace` has no `FreeTypeFont` for `ImageDraw.text`. Cached per
    `(path, char, scale)`. A zero-size (no-op) mask for an ink-less glyph
    or an unloadable file; never raises.
    """
    font = cft_fonts.load(path)
    if font is None:
        return Image.new("L", (0, 0))
    glyph = font.glyph(char)
    if glyph.advance <= 0 or glyph.height <= 0:
        return Image.new("L", (0, 0))
    max_level = font.max_level or 1
    data = bytes(level * 255 // max_level for level in glyph.levels)
    mask = Image.frombytes("L", (glyph.advance, glyph.height), data)
    if scale != 1:
        mask = mask.resize((glyph.advance * scale, glyph.height * scale), Image.NEAREST)
    return mask


class _Renderer:
    def __init__(self, resolved, draw, image, scale, values, options, used_faces=None) -> None:
        self.resolved = resolved
        self.draw = draw
        self.image = image
        self.scale = scale
        self.values = values
        self.options = options
        #: `render`'s own `used_faces`, or `None` -- see `_system_face`.
        self.used_faces = used_faces

    def _system_face(self, metric: FontMetric, *, scale: float | None = None):
        """`fallback.system_face` at `scale` (default `self.scale`), with
        `PreviewOptions.fonts_root` threaded through and the resolved face
        recorded into `self.used_faces` for `stand_in_warning`. Every system
        or vector face this renderer draws with comes through here."""
        face = fallback.system_face(metric, scale=self.scale if scale is None else scale,
                                    fonts_root=self.options.fonts_root)
        if self.used_faces is not None and face is not None:
            self.used_faces.setdefault(metric, face)
        return face

    # -- aod: restyling -----------------------------------------------------
    #
    # The host twins of `wfb.emit.monkeyc.common.AodStyle`: while `--aod`
    # renders, an element's own resolved `aod:` override for a key wins;
    # a colour with no override is dimmed by the face's `aod: {dim: ...}`.

    def _aod_field(self, element, key: str, base):
        """``base``, replaced by this element's resolved `aod:` override for
        ``key`` while `--aod` renders and one is set."""
        if not self.options.aod or element.aod is None:
            return base
        override = getattr(element.aod, key)
        return override if override is not None else base

    def _aod_geometry(self, placed, key: str, base):
        """``base`` (a resolved pixel length), replaced by ``placed.aod_<key>``
        (`thickness`, `bar_width`) while `--aod` renders and it is set. A
        `hands`/`pattern` override applies uniformly to every part."""
        override = getattr(placed, f"aod_{key}") if self.options.aod else None
        return base if override is None else override

    def _dim_rgb(self, rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        """`aod: {dim: ...}` applied to a resolved RGB triple, through the
        same integer arithmetic (`wfb.palette.Color.dim`) both codegen paths
        use, so a colour dims to the identical value here and on the device."""
        num, den = dim_fraction(self.resolved.face.aod_dim)
        dimmed = Color(*rgb).dim(num, den)
        return (dimmed.r, dimmed.g, dimmed.b)

    def _aod_color(self, element, key: str, base_expr,
                   values: dict | None = None) -> tuple[int, int, int]:
        """The drawn RGB for one colour role (`color`/`track_color`/
        `icon_color`): this element's own `aod:` override for ``key`` while
        `--aod` renders, else ``base_expr`` (evaluated against ``values``),
        dimmed when the face has `aod: {dim: ...}` and no override took over.
        A `hands`/`pattern` part passes its own colour as ``base_expr`` and
        ``key="color"``: the element-level override applies to every part.

        Which of the three applies is `aod_color_choice` (`wfb.ir`), the same
        decision `wfb.emit.monkeyc.common.AodStyle.color`/`.part_color` read
        for Monkey C -- this method only turns it into an RGB triple."""
        base = self._color(base_expr, values)
        if not self.options.aod or element.aod is None:
            return base
        choice, override = aod_color_choice(element.aod, key, self.resolved.face.aod_dim is not None)
        if choice == "override":
            return self._color(override)
        if choice == "dim":
            return self._dim_rgb(base)
        return base

    # -- dispatch ---------------------------------------------------------

    def render_element(self, placed) -> None:
        # `--aod`: the fully resolved AOD gate (`element.visible` already
        # folded in), which an `aod: {visible: ...}` may narrow further.
        visible = (placed.element.aod.visible if self.options.aod and placed.element.aod
                   else placed.element.visible)
        if not self._visible(visible):
            return
        kinds.for_placed(placed).draw_preview(self, placed)

    # -- elements ---------------------------------------------------------

    def _shape(self, placed: PlacedShape) -> None:
        element = placed.element
        fill = self._aod_color(element, "color", element.color)
        filled = self._aod_field(element, "filled", element.filled)
        thickness = self._aod_geometry(placed, "thickness", placed.thickness)
        s = self.scale
        if element.shape == "rectangle":
            box = self._rect(placed.rect or placed.box)
            if filled:
                self.draw.rectangle(box, fill=fill)
            else:
                self.draw.rectangle(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "rounded_rectangle":
            box = self._rect(placed.rect or placed.box)
            radius = placed.corner_radius * s
            if filled:
                self.draw.rounded_rectangle(box, radius=radius, fill=fill)
            else:
                self.draw.rounded_rectangle(box, radius=radius, outline=fill,
                                            width=max(1, thickness * s))
        elif element.shape == "arc":
            # Same whole-degree rule the generated code gets from
            # WfbArc.drawSpan -- see `arc_span`.
            cx, cy = placed.center[0] * s, placed.center[1] * s
            r = placed.radius * s
            span = arc_span(placed.start_angle, placed.sweep)
            if r > 0 and span is not None:
                self.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
                              fill=fill, width=max(1, thickness * s))
        elif element.shape == "ellipse":
            cx, cy = placed.center
            rx, ry = placed.rx, placed.ry
            box = [(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s]
            if filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "polygon":
            if len(placed.points) >= 3:
                self.draw.polygon([(x * s, y * s) for x, y in placed.points], fill=fill)
        elif element.shape == "circle":
            cx, cy = placed.center
            r = placed.radius
            box = [(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s]
            if filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, thickness * s))
        elif element.shape == "line":
            self.draw.line(
                [placed.center[0] * s, placed.center[1] * s, placed.end[0] * s, placed.end[1] * s],
                fill=fill, width=max(1, thickness * s),
            )

    def _hands(self, placed: PlacedHands) -> None:
        """`type: hands` -- the same three angle rules `runtime-lib/
        WfbHands.mc` computes on the device (`wfb.layout.HAND_ANGLES`'s own
        `host` half), applied to the *resolved* geometry so this can never
        disagree with the generated code about a hand's shape or its axis.

        `--asleep` (or `--aod`, which implies it) hides an `awake`-only
        second hand, the same choice the generated view makes while
        `_sleeping`; a `seconds: never` hand was already excluded at resolve
        time.
        """
        element = placed.element
        s = self.scale
        cx, cy = placed.center[0] * s, placed.center[1] * s
        hour = int(self.values.get("time.hour", 0) or 0)
        minute = int(self.values.get("time.minute", 0) or 0)
        second = int(self.values.get("time.second", 0) or 0)
        angles = {
            name: HAND_ANGLES[name].host(hour, minute, second)
            for name in ("hour", "minute", "second")
        }
        asleep = self.options.asleep or self.options.aod
        for hand_name in ("hour", "minute", "second"):
            hand = getattr(placed, hand_name)
            if hand is None:
                continue
            if hand_name == "second" and element.seconds == "awake" and asleep:
                continue
            sin_t, cos_t = math.sin(angles[hand_name]), math.cos(angles[hand_name])
            for part in hand.parts:
                self._hand_part(placed, part, cx, cy, sin_t, cos_t)

    def _hand_part(self, placed: PlacedHands | PlacedPattern, part, cx: float, cy: float,
                   sin_t: float, cos_t: float, values: dict | None = None) -> None:
        """One polygon/line/circle part of a hand or pattern copy, its
        vertices rotated by `(sin_t, cos_t)` about the scaled `(cx, cy)`.
        The element-level `aod:` colour/thickness override applies to every
        part (`_aod_color`, `_aod_geometry`)."""
        s = self.scale
        fill = self._aod_color(placed.element, "color", part.color, values)
        thickness = self._aod_geometry(placed, "thickness", part.thickness)

        def rotated(x: float, y: float) -> tuple[float, float]:
            return (cx + (x * cos_t - y * sin_t) * s, cy + (x * sin_t + y * cos_t) * s)

        if part.shape == "polygon":
            if len(part.points) >= 3:
                self.draw.polygon([rotated(x, y) for x, y in part.points], fill=fill)
        elif part.shape == "line":
            x1, y1 = rotated(part.x1, part.y1)
            x2, y2 = rotated(part.x2, part.y2)
            self.draw.line([x1, y1, x2, y2], fill=fill, width=max(1, thickness * s))
        else:  # circle
            x, y = rotated(part.x, part.y)
            r = part.radius * s
            box = [x - r, y - r, x + r, y + r]
            if part.filled:
                self.draw.ellipse(box, fill=fill)
            else:
                self.draw.ellipse(box, outline=fill, width=max(1, thickness * s))

    def _pattern(self, placed: PlacedPattern) -> None:
        """`type: pattern` -- one template, drawn once per copy through
        :meth:`PlacedPattern.transform`: the very same `(ox, oy, sin, cos)`
        the generated draw method computes on the device. Copies draw
        ascending, parts in list order within a copy -- the generated
        nested-loop order. A polygon/line/circle part reuses `_hand_part`;
        an `arc` part turns its start angle with the copy instead
        (`_pattern_arc`); a `text` part draws at the copy's own rounded
        anchor (`_pattern_text`).

        `when_absent: hide` is checked once for the whole element
        (`_pattern_absent`), the device's own pre-loop null guard. Per copy,
        each part's own `visible:` is evaluated with `copy` bound, the same
        `values` its colour uses.
        """
        element = placed.element
        if self._pattern_absent(element):
            return
        s = self.scale
        for index in placed.copies:
            ox, oy, sin_t, cos_t = placed.transform(index)
            # `copy` is the generated loop's `i`: a colour reading it is
            # evaluated afresh for every copy, exactly as the device does.
            values = {**self.values, expr.COPY: index}
            for part_index, part in enumerate(placed.parts):
                if not self._visible(element.parts[part_index].visible, values):
                    continue
                if part.shape == "arc":
                    self._pattern_arc(placed, part, ox, oy, index, values)
                elif part.shape == "text":
                    self._pattern_text(placed, part, ox, oy, sin_t, cos_t, index, values)
                else:
                    self._hand_part(placed, part, ox * s, oy * s, sin_t, cos_t, values)

    def _pattern_absent(self, element) -> bool:
        """Whether any nullable source this pattern's colours
        (`element.colors`: the default plus every part's own) or any part's
        own `visible:` reads is absent in the sample -- the host mirror of
        the null guard the device emits before its copy loop
        (`wfb.emit.monkeyc.rotated._emit_pattern`, fed by the same
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
            catalog.CATALOG[path].guard_needed and self.values.get(path) is None
            for path in sources
        )

    def _pattern_arc(self, placed: PlacedPattern, part, ox: float, oy: float, index: int,
                     values: dict) -> None:
        """An `arc` template part -- always centred on the copy's own origin
        (`at:` is rejected on it), so only its *start angle* turns with the
        copy, as `WfbArc.drawSpan` is called on the device: `part.start_angle
        + start + index * step` (plain `part.start_angle` for a linear
        pattern, whose `start`/`step` are `0`)."""
        s = self.scale
        fill = self._aod_color(placed.element, "color", part.color, values)
        thickness = self._aod_geometry(placed, "thickness", part.thickness)
        cx, cy = ox * s, oy * s
        r = part.radius * s
        author_start = part.start_angle + placed.start + index * placed.step
        span = arc_span(author_start, part.sweep)
        if r > 0 and span is not None:
            self.draw.arc([cx - r, cy - r, cx + r, cy + r], *span,
                          fill=fill, width=max(1, thickness * s))

    def _pattern_text(self, placed: PlacedPattern, part, ox: float, oy: float,
                      sin_t: float, cos_t: float, index: int, values: dict) -> None:
        """A `shape: text` template part, drawn at this copy's own anchor,
        rounded half-up the way `runtime-lib/WfbGeom.mc`'s `rotatedX`/
        `rotatedY` round it (:func:`pattern_text_anchor`), through the same
        `_draw_text`/`_draw_vector_text` a `text` element uses.

        A baked/system font draws upright glyphs. A `face:` font's `curve:`
        turns them, at the part's own local angle composed with this copy's
        rotation (:class:`~wfb.layout.PatternTextAngle`), the composition
        codegen (`_emit_pattern_text_angle_expr`) and the lint box
        (`wfb.layout._pattern_text_ink`) also perform. `outline:` stamps the
        already-transformed anchor, so the ring is a screen-space translation
        at every copy.
        """
        text = part.texts[index]
        color = self._aod_color(placed.element, "color", part.color, values)
        anchor = pattern_text_anchor(part, ox, oy, sin_t, cos_t)
        ring_color = (
            self._color(part.outline_color, values) if part.outline_color is not None else None
        )
        if part.font_is_vector:
            if not part.font_available:
                return  # `if_unavailable: hide` on this device
            angle = (
                PatternTextAngle(part.curve_angle_garmin, placed.start, placed.step)
                .copy_curve_angle(index) if part.curve_style is not None else 0.0
            )

            def draw(at, fill, box=None):
                self._draw_vector_text(
                    text, at, part.align, part.vertical_align, part.font_metric, fill,
                    part.curve_style, angle, part.curve_radius_px, part.curve_direction)
        else:
            font: BakedFont | None = (
                self.resolved.fonts.get(part.font_reference) if part.font_is_custom else None
            )

            def draw(at, fill, box=None):
                self._draw_text(font, text, at, part.align, part.vertical_align,
                                part.font_metric, fill)
        self._draw_outlined(draw, anchor, color, ring_color, part.outline_width)

    def _draw_outlined(self, draw: Callable[..., None], anchor: tuple[int, int], color,
                       ring_color, ring_width: int, box=None) -> None:
        """`draw(anchor, color, box)` once for the interior, preceded by one
        ring-coloured stamp per `wfb.ir.disc_perimeter_offsets(ring_width)`
        offset when `ring_color` is set -- the host twin of the codegen stamp
        loop, using the same offset table, so preview and device stamp the
        same pixels. `anchor` and the offsets are device pixels; `draw`
        applies the preview's own upscale. Only the interior gets `box` (the
        "no face at all" outline fallback)."""
        if ring_color is not None:
            ax, ay = anchor
            for dx, dy in disc_perimeter_offsets(ring_width):
                draw((ax + dx, ay + dy), ring_color)
        draw(anchor, color, box)

    def _text(self, placed: PlacedText) -> None:
        element = placed.element
        text = self._text_value(placed)
        if text is None:
            return
        color = self._aod_color(element, "color", element.color)
        if placed.font_is_vector:
            # A `face:` font draws upright, angled or radial, never through a
            # baked sheet; `font_available is False` is `if_unavailable: hide`
            # on this device, which draws nothing, as the watch does.
            if not placed.font_available:
                return

            def draw(anchor, fill, box=None):
                self._draw_vector_text(
                    text, anchor, element.align, element.vertical_align, placed.font_metric,
                    fill, placed.curve_style, placed.curve_angle_garmin,
                    placed.curve_radius_px, placed.curve_direction, box=box)
        else:
            font, metric = self._text_font(placed)

            def draw(anchor, fill, box=None):
                self._draw_text(font, text, anchor, element.align, element.vertical_align,
                                metric, fill, box=box)
        outline = element.outline
        self._draw_outlined(draw, placed.anchor_point, color,
                            self._color(outline.color) if outline is not None else None,
                            outline.width if outline is not None else 0, box=placed.box)

    def _text_font(self, placed: PlacedText) -> tuple[BakedFont | None, FontMetric | None]:
        """The baked font (or `None` for a system one) and metric a non-vector
        `text` element draws with, after its `aod: {font: ...}` override --
        the same scope as codegen's `wfb.emit.monkeyc.shapes._emit_text_draw`:
        an override naming a *different* baked font swaps the sheet, one
        naming a system `FONT_*` swaps the metric. A vector override is a
        build error (`Builder._build_aod_authored`), so the `is_vector`
        check is defensive."""
        element = placed.element
        font: BakedFont | None = (
            self.resolved.fonts.get(placed.font_reference) if placed.font_is_custom else None
        )
        metric = placed.font_metric
        aod_font = self._aod_field(element, "font", None)
        if aod_font is None or aod_font == placed.font_reference:
            return font, metric
        if element.aod.font_is_custom:
            override_spec = self.resolved.face.fonts.get(aod_font)
            if override_spec is not None and not override_spec.is_vector:
                override_font = self.resolved.fonts.get(aod_font)
                if override_font is not None:
                    return override_font, None
        else:
            override_metric = self.resolved.device.system_fonts.get(aod_font)
            if override_metric is not None:
                return None, override_metric
        return font, metric

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
        present = ([v for v in values if v is not None]
                  if element.min_auto or element.max_auto else [])
        if element.min_auto:
            lo = min(present) if present else 0.0
        else:
            lo = self._graph_bound(element.min, 0.0)
        if element.max_auto:
            hi = max(present) if present else 1.0
        else:
            hi = self._graph_bound(element.max, 1.0)
        span = hi - lo
        if span <= 0:
            span = 1.0
        color = self._aod_color(element, "color", element.color)
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
                thickness = self._aod_geometry(placed, "thickness", placed.thickness)
                self.draw.line([previous, point], fill=color, width=max(1, thickness * s))
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
        y = placed.box.y
        h = placed.size[1]
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
        bar_width = self._aod_geometry(placed, "bar_width", placed.bar_width)
        for i, value in enumerate(values):
            if value is None:
                continue
            bar_height = max(1, round((value - lo) * h / span))
            left = (x + i * pitch + (pitch - bar_width) / 2) * s
            top = (y + h - bar_height) * s
            self.draw.rectangle(
                [left, top, left + bar_width * s - 1, (y + h) * s - 1], fill=color
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
        color = self._aod_color(element, "color", element.color)
        if element.icon_color is not None:
            icon_color = self._aod_color(element, "icon_color", element.icon_color)
        else:
            # No awake `icon_color:` at all falls back to whatever colour
            # `color` (above) already resolved to -- matches codegen's own
            # "icon draws in the text's colour by default" rule exactly
            # (`wfb.emit.monkeyc.complication_slot._emit_complication_slot`).
            icon_aod = (
                element.aod.icon_color if (self.options.aod and element.aod is not None) else None
            )
            icon_color = self._color(icon_aod) if icon_aod is not None else color
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
        elif placed.font_metric is not None:
            # `fallback.measure`'s second return is whether real metrics were
            # used, not a height -- `wfb.layout.Resolver._resolve_complication_
            # slot` uses `fallback.line_height` for exactly this case, and
            # this mirrors it. `fonts_root` matches `_system_face` below (the
            # same `PreviewOptions.fonts_root` every other measurement this
            # renderer makes goes through), so a slot's box is sized from the
            # same file it is then drawn with (plan 18 item 8).
            text_width, _ = fallback.measure(text, placed.font_metric,
                                             fonts_root=self.options.fonts_root)
            text_height = fallback.line_height(placed.font_metric, fonts_root=self.options.fonts_root)
        else:
            text_width, text_height = 0, placed.font_px

        glyph_obj = _baked_glyph(icon_font, icon_glyph)
        icon_width, icon_height = icon_font.measure(icon_glyph) if glyph_obj else (0, 0)

        # One shared geometry function for every position --
        # `wfb.layout.complication_slot_pair_geometry`, the same one
        # `Resolver._resolve_complication_slot` uses to size the estimated
        # box, called here with the *actual* measured extents this preview
        # already has (unlike layout, which only has an estimate).
        geometry = complication_slot_pair_geometry(
            placed.icon_position, icon_width, icon_height, text_width, text_height,
            placed.icon_gap_px,
        )
        ax, ay = placed.anchor_point
        # `align`/`vertical_align` move the pair off the anchor -- the same
        # `wfb.layout.alignment_shift` rule every other kind's preview
        # uses, mirroring the arithmetic
        # `wfb.emit.monkeyc.complication_slot._emit_complication_slot` computes at runtime
        # from its own (real, pulled) measurements. center/center adds
        # exactly `0.0`.
        dx, dy = alignment_shift(geometry.width, geometry.height, element.align, element.vertical_align)
        origin_x = ax + dx - geometry.width / 2
        origin_y = ay + dy - geometry.height / 2

        if glyph_obj is not None:
            self._paste_glyph(icon_font.sheet, glyph_obj,
                              (origin_x + geometry.icon_x) * s,
                              (origin_y + geometry.icon_y) * s, icon_color)

        pen_x = origin_x + geometry.text_x
        top = origin_y + geometry.text_y
        if text_font is not None and text_font.sheet is not None:
            self._blit_baked_line(text_font, text, pen_x * s, top * s, color)
            return
        if placed.font_metric is not None:
            face = self._system_face(placed.font_metric, scale=s)
            if face is not None:
                # `top` is the text box's own top edge (`geometry.text_y`,
                # sized from `fallback.line_height` above); draw at its
                # baseline, the same line-box model `_approximate_text` uses
                # -- `wfb.fonts.fallback.SystemFace.baseline`, not Pillow's
                # own ascender-based anchor, which would not agree with the
                # box `wfb.layout` sized this pair from.
                self._draw_system_line(face, pen_x * s, top * s + face.baseline,
                                       text, color)

    def _complication_slot_text(self, element, ctype) -> str:
        """An illustrative reading for `ctype`, formatted the same way
        `wfb.emit.monkeyc.complication_slot._emit_complication_slot` renders one: an optional
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
        spec = self._aod_field(element, "format", element.format) or "{}"
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
                   align: str, vertical_align: str, metric: FontMetric | None,
                   color: tuple[int, int, int], box=None) -> None:
        """Draw `text` upright at `anchor` -- through the baked sheet when
        `font` is a custom one, the device's own typeface (or its stand-in)
        otherwise. Shared by `_text` and `_pattern_text`. `box` is only the
        "no scalable system face at all" outline fallback of
        `_approximate_text`; a pattern part has none to give.
        """
        if font is not None:
            self._blit_bitmap_text(font, text, anchor, align, vertical_align, metric, color, box)
        else:
            self._approximate_text(text, anchor, align, vertical_align, metric, color, box)

    def _blit_bitmap_text(self, font: BakedFont, text: str, anchor: tuple[int, int],
                          align: str, vertical_align: str, metric: FontMetric | None,
                          color: tuple[int, int, int], box=None) -> None:
        """Draw with the *baked sheet*, so the preview shows the real glyphs."""
        if font.sheet is None:
            self._approximate_text(text, anchor, align, vertical_align, metric, color, box)
            return
        s = self.scale
        width, _ = font.measure(text)
        x, y = anchor[0] * s, anchor[1] * s
        line_height = font.line_height * s
        # The one shared placement rule (`wfb.layout.alignment_shift`), not
        # a private dict literal -- `bottom` puts the ink's bottom edge on
        # `y`, rather than drawing it hanging down from `y` like `top` does.
        dx, dy = alignment_shift(width * s, line_height, align, vertical_align)
        left = x + dx - width * s / 2
        top = y + dy - line_height / 2
        self._blit_baked_line(font, text, left, top, color)

    def _blit_baked_line(self, font: BakedFont, text: str, left: float, top: float,
                         color: tuple[int, int, int]) -> None:
        """Paste `text`'s baked glyphs pen-wise from the (already scaled)
        top-left of their line box, skipping any glyph the sheet lacks."""
        pen = left
        for char in text:
            glyph = font.glyphs.get(char)
            if glyph is None:
                continue
            self._paste_glyph(font.sheet, glyph, pen, top, color)
            pen += glyph.xadvance * self.scale

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
                          vertical_align: str, metric: FontMetric | None, color, box=None) -> None:
        """Draw system-font text from its own line box: the box top is
        `anchor_y - {top: 0, center: line_height/2, bottom: line_height}`
        (`wfb.layout.alignment_shift`'s vertical rule, the same top edge
        `PlacedText.box` and the lint box use), and glyphs are drawn at
        `top + baseline`. Never Pillow's own vertical anchors, which measure
        the *stand-in* face's ascender/descender and would disagree with the
        line height the metric defines.

        A `substitute`/`none` match draws through this same path: the glyph
        *shapes* differ from the watch's, but position and extent are exact,
        because layout measured with this very face.
        """
        if metric is None:
            # No pixel metrics for this symbol on this device at all
            # (`_font_for_ref`'s own "no pixel metrics" warning already
            # covers it) -- nothing to measure or draw with; mark the extent
            # instead, the same "more honest than drawing at the wrong size"
            # fallback the "no scalable face at all" case below uses.
            self._mark_extent(box)
            return
        s = self.scale
        face = self._system_face(metric, scale=s)
        if face is None:
            # No scalable face at all (older Pillow with no scalable
            # default, and no TTF located either): fall back to marking the
            # extent, which is more honest than drawing text at the wrong
            # size -- only possible for a `text` element, which has a `box`
            # to outline; a pattern text part (`box is None`) simply draws
            # nothing here.
            self._mark_extent(box)
            return

        x = anchor[0] * s
        y = anchor[1] * s
        top = y - {"top": 0, "center": face.line_height / 2, "bottom": face.line_height}[vertical_align]
        baseline_y = top + face.baseline
        # "left"/"right" share Pillow's own first letter; anything else
        # (only "center" is a valid value here) is the middle anchor.
        width = face.width(text)
        left = x - {"left": 0, "right": width}.get(align, width / 2)
        self._draw_system_line(face, left, baseline_y, text, color)

    def _draw_system_line(self, face, left: float, baseline_y: float, text: str, color,
                          *, draw=None, image=None) -> None:
        """Draw a system-font line glyph by glyph, each on the pen position
        `SystemFace.advances` gives -- the advances `wfb.layout` measured
        with, not Pillow's own layout, which disagrees with the device by up
        to a pixel per glyph. A bitmap face (`face.bitmap` set) has no
        `FreeTypeFont` and pastes each `.cft` cell instead
        (`_draw_bitmap_line`). `draw`/`image` default to the canvas;
        `_paste_rotated_run` passes a throwaway layer to rotate.
        """
        draw = self.draw if draw is None else draw
        image = self.image if image is None else image
        if face.bitmap is not None:
            self._draw_bitmap_line(face, left, baseline_y, text, color, image=image)
            return
        pen = left
        for char, advance in zip(text, face.advances(text)):
            draw.text((pen, baseline_y), char, fill=color, font=face.font, anchor="ls")
            pen += advance

    def _draw_bitmap_line(self, face, left: float, baseline_y: float, text: str, color,
                          *, image=None) -> None:
        """The bitmap half of `_draw_system_line`: paste each glyph's own
        `.cft` cell (`_bitmap_glyph_mask`) with its top `face.baseline` above
        the shared baseline, tinted `color` through its ink levels."""
        image = self.image if image is None else image
        s = self.scale
        top = baseline_y - face.baseline
        pen = left
        for char, advance in zip(text, face.advances(text)):
            mask = _bitmap_glyph_mask(face.path, char, s)
            if mask.size[0] and mask.size[1]:
                tint = Image.new("RGB", mask.size, color)
                image.paste(tint, (int(round(pen)), int(round(top))), mask)
            pen += advance

    # -- vector fonts / curve: (plan 11) -----------------------------------

    def _draw_vector_text(
        self, text: str, anchor_point: tuple[int, int], align: str, vertical_align: str,
        font_metric, color, curve_style: str | None, curve_angle_garmin: float,
        curve_radius_px: int, curve_direction: str | None, *, box=None,
    ) -> None:
        """A `face:` (vector) font's draw -- upright (`curve_style is None`,
        exactly like a system font, `_approximate_text`), `angled`
        (`Dc.drawAngledText`: the whole string rotated about the anchor) or
        `radial` (`Dc.drawRadialText`: per-glyph placement around a circle).
        Shared by `_text` and `_pattern_text` (which passes its copy's own
        anchor and copy-composed angle). `box` is the upright path's "no
        scalable face" outline fallback.

        **`curve_angle_garmin` is Garmin's convention throughout** (degrees
        counter-clockwise from 3 o'clock, screen y down), the same one
        `wfb.layout.rotated_rect_corners` rotates the lint box by, verified
        against the SDK's `TrueTypeFontsAngledText` sample. Getting the sign
        backwards would silently mirror every curved element.
        """
        if curve_style is None:
            # Delegates to `_approximate_text` wholesale, including its own
            # "no scalable face at all" fallback (an outline box, `box=box`)
            # -- that edge case is exactly as reachable, and exactly as
            # handled, for a vector font as for a system one.
            self._approximate_text(text, anchor_point, align, vertical_align,
                                   font_metric, color, box=box)
            return
        face = self._system_face(font_metric)
        if face is None:
            return  # same rare fallback; angled/radial have no box to outline
        s = self.scale
        if curve_style == "angled":
            x, y = anchor_point[0] * s, anchor_point[1] * s
            self._paste_rotated_run(face, text, curve_angle_garmin,
                                    align, vertical_align, (x, y), color,
                                    font_metric=font_metric)
        else:
            self._draw_radial_vector_text(
                anchor_point, curve_radius_px, curve_angle_garmin, curve_direction,
                face, text, align, vertical_align, color, font_metric)

    def _draw_radial_vector_text(
        self, anchor_point: tuple[int, int], curve_radius_px: int,
        curve_angle_garmin: float, curve_direction: str | None,
        face, text: str, align: str, vertical_align: str, color,
        font_metric=None,
    ) -> None:
        """`curve: {style: radial}` -- each glyph is its own tiny "angled"
        run (`_paste_rotated_run`), placed around the circle of
        `curve_radius_px` centred on `anchor_point` (radial `at:` is the
        centre).

        **Facing: `clockwise` faces outward, `counter_clockwise` inward** --
        standard text-on-a-path behaviour, verified in both directions
        against the real simulator (2026-09-21, `fenix8solar47mm`,
        `examples/features/vector-text/`; `docs/research/12-vector-fonts.md`).
        A glyph's local "up" `(0, -1)` must map onto the outward radial
        `(cos pos, -sin pos)` (clockwise) or inward `(-cos pos, sin pos)`
        (counter-clockwise) at its circle position `pos`, which solves to a
        glyph rotation of `pos - 90` or `pos + 90` respectively.

        **Pen direction:** `clockwise` walks the string with *decreasing*
        Garmin angle, `counter_clockwise` with increasing (the SDK's
        `RADIAL_TEXT_SCENARIO`: `angle=0, CLOCKWISE, LEFT` reads from 3
        o'clock toward 6). In both facings the glyph's mapped local "right"
        then equals the arc's walking direction, so reading order is right.

        `align` places the whole string along the arc as
        `TEXT_JUSTIFY_LEFT/CENTER/RIGHT` would (starting, centred on or
        ending at the angle). Each glyph is pasted `align: "center"` at the
        arc position of the *middle* of its own advance, rotated for that
        same angle, so every glyph's midline lies on its own radius like a
        spoke -- verified on the simulator (2026-09-21, `fenix8solar51mm`).
        `font_metric` lets `_paste_rotated_run` refetch this face
        supersampled.
        """
        s = self.scale
        radius = curve_radius_px * s
        if radius <= 0:
            return
        cx, cy = anchor_point[0] * s, anchor_point[1] * s
        advances = face.advances(text)
        total = sum(advances)
        align_offset = radial_align_offset(align, total)
        counter_clockwise = curve_direction == "counter_clockwise"
        direction_sign = radial_direction_sign(curve_direction)
        # Facing: outward (`pos - 90`) for clockwise, inward (`pos + 90`)
        # for counter_clockwise -- see the derivation above.
        facing_offset = 90.0 if counter_clockwise else -90.0
        # `bottom`: the device's native no-`VCENTER` mode puts the BASELINE
        # on the circle (`wfb.layout.radial_text_band`'s device model), so
        # each glyph's box top sits one ascent toward its own "up" --
        # outward when facing out, inward when facing in -- and is pasted
        # `top`-aligned from there. `top`/`center` are the box edge/centre
        # on the circle already, which `_paste_rotated_run` does as-is.
        glyph_vertical_align = vertical_align
        glyph_radius = radius
        if vertical_align == "bottom":
            glyph_vertical_align = "top"
            glyph_radius = radius + (-face.baseline if counter_clockwise else face.baseline)
        base_theta = math.radians(curve_angle_garmin)
        pen = 0.0
        for char, advance in zip(text, advances):
            pixel_offset = pen + advance / 2.0 - align_offset
            theta_pos = base_theta + direction_sign * (pixel_offset / radius)
            px = cx + glyph_radius * math.cos(theta_pos)
            py = cy - glyph_radius * math.sin(theta_pos)
            glyph_angle_garmin = math.degrees(theta_pos) + facing_offset
            self._paste_rotated_run(face, char, glyph_angle_garmin, "center",
                                    glyph_vertical_align, (px, py), color,
                                    font_metric=font_metric)
            pen += advance

    def _paste_rotated_run(self, face, run: str, angle_garmin_degrees: float,
                           align: str, vertical_align: str,
                           anchor_xy: tuple[float, float], color,
                           font_metric: FontMetric | None = None) -> None:
        """Render `run` upright, rotate it by `angle_garmin_degrees` about the
        point `align`/`vertical_align` would place it at, and composite it so
        that point lands at `anchor_xy` (scaled preview pixels). Shared by
        `angled` (the whole string) and `radial` (one glyph at a time).

        The paste offset runs `wfb.layout.rotated_rect_corners`' own rotation
        (`cx = dx*cos + dy*sin`, `cy = -dx*sin + dy*cos`) forward on the
        alignment shift, so the preview rotates about the same point the
        lint box does. `Image.rotate` turns counter-clockwise for a positive
        angle, Garmin's own positive sense, so the angle passes straight
        through.

        **Rasterised, not resampled.** Garmin rotates the *outline* and then
        rasterises; rotating an already-aliased bitmap softens stems. So an
        outline face is refetched at `_ROTATED_TEXT_SUPERSAMPLE`x the preview
        scale (same `font_metric`, through `_system_face`), drawn onto a
        layer that much larger, rotated, and `LANCZOS`-downsampled back.
        **Geometry does not move**: every placement number (`width`,
        `line_height`, `pad`, the layer size, `dx`/`dy`, `top_left`) comes
        from `face` at the ordinary scale; `tests/test_vector_text_preview.py`
        checks the centre of mass moves under a pixel with supersampling on
        vs off. A bitmap (`.cft`) face has no outline to supersample and keeps
        `ss = 1` (defensive -- only outline faces are published as `face:`).
        """
        if not run:
            return
        width = face.width(run)
        line_height = face.line_height
        if width <= 0 or line_height <= 0:
            return
        pad = max(2, int(math.ceil(line_height * 0.2)))
        layer_w = int(math.ceil(width)) + 2 * pad
        layer_h = int(math.ceil(line_height)) + 2 * pad

        ss = 1
        render_face = face
        if face.bitmap is None and font_metric is not None:
            candidate = self._system_face(font_metric, scale=self.scale * _ROTATED_TEXT_SUPERSAMPLE)
            if candidate is not None and candidate.bitmap is None:
                render_face = candidate
                ss = _ROTATED_TEXT_SUPERSAMPLE

        layer = Image.new("RGBA", (layer_w * ss, layer_h * ss), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        local_left = float(pad) * ss
        local_baseline_y = pad * ss + render_face.baseline
        self._draw_system_line(render_face, local_left, local_baseline_y, run, color,
                               draw=layer_draw, image=layer)
        rotated = layer.rotate(angle_garmin_degrees, resample=Image.BICUBIC, expand=True)
        if ss != 1:
            downsampled_size = (max(1, round(rotated.width / ss)),
                                max(1, round(rotated.height / ss)))
            rotated = rotated.resize(downsampled_size, Image.LANCZOS)
        theta = math.radians(angle_garmin_degrees)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        dx, dy = alignment_shift(width, line_height, align, vertical_align)
        offset_x = dx * cos_t + dy * sin_t
        offset_y = -dx * sin_t + dy * cos_t
        ax, ay = anchor_xy
        top_left = (int(round(ax + offset_x - rotated.width / 2.0)),
                   int(round(ay + offset_y - rotated.height / 2.0)))
        self.image.paste(rotated, top_left, rotated)

    # -- shared -----------------------------------------------------------

    def _mark_extent(self, box) -> None:
        """Outline `box` in dark grey where text cannot be drawn at its real
        size -- `_approximate_text`'s two fallbacks.

        An empty box draws nothing. Unmeasured text gets exactly that: with
        no metric, layout has no extent to give it and records a 0x0 box at
        the anchor (every system font on a device missing from the scraped
        SDK reference, e.g. the fenix 9 family), and `_rect` turns a 0-wide
        box into an inverted rectangle that Pillow rejects outright.
        """
        if box is None or box.width <= 0 or box.height <= 0:
            return
        self.draw.rectangle(self._rect(box), outline=(64, 64, 64), width=1)

    def _rect(self, box) -> list[float]:
        s = self.scale
        return [box.x * s, box.y * s, box.right * s - 1, box.bottom * s - 1]

    def _visible(self, expression, values: dict | None = None) -> bool:
        """`visible:` -- the same rule the device runs, on the sample
        readings (`self.values`, or a pattern part's own `values` with
        `copy` bound to the copy being drawn -- `values` overrides
        `self.values` the same way `_color`'s does).

        Absent means hidden, so `expr.evaluate` returning ``None`` (which is
        exactly what it does when any input is missing) hides the element,
        matching the generated `if (x == null || !(cond)) return;` rather than
        merely approximating it.  A group's condition is already conjoined into
        every descendant by `wfb.ir`, so nothing here has to walk the tree --
        which is also why the preview cannot silently disagree with the device
        about a subtree.  `expression is None` means "no condition authored" --
        an element with no `visible:`, or a pattern part with none of its own.
        """
        if expression is None:
            return True
        if expression.constant is not None:
            return bool(expression.constant)
        if expression.ast is None:
            return True
        return bool(expr.evaluate(expression.ast, self.values if values is None else values))

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


def _baked_glyph(font: BakedFont | None, char: str | None):
    """`char`'s `GlyphBox` in `font`, or `None` when there is no font, no
    sheet to crop from, or no such glyph -- the one "can this baked glyph
    be drawn" check `_icon` and `_complication_slot` share."""
    if font is None or font.sheet is None or char is None:
        return None
    return font.glyphs.get(char)


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


def save(image: Image.Image, path: Path) -> Path:
    """Write ``image`` to ``path`` as a PNG, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path
