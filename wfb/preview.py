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

from . import aod_mask, expr, kinds
from .devices import FontMetric
from .fonts import BakedFont, fallback
from .fonts import cft as cft_fonts
from .ir import aod_color_choice, disc_perimeter_offsets
from .layout import (
    PlacedHands, PlacedPattern, ResolvedFace,
    alignment_shift,
    radial_align_offset, radial_direction_sign,
)
from .palette import MIP64_LEVELS, Color, dim_fraction

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
    #: (`Renderer.aod_field`/`aod_color`). A design with no `aod:`
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
    renderer = Renderer(resolved, draw, image, scale, values, options, used_faces)
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
    `Renderer._draw_bitmap_line` pastes a colour through, since a bitmap
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


@dataclass(frozen=True)
class _BakedGlyphs:
    """A text's glyphs from its baked BMFont sheet (`Renderer.glyph_source`):
    the real pixels the device draws. Sizes are in scaled preview pixels."""

    font: BakedFont
    scale: int

    @property
    def line_height(self) -> float:
        return self.font.line_height * self.scale

    def width(self, text: str) -> float:
        return self.font.measure(text)[0] * self.scale

    def draw(self, renderer: "Renderer", left: float, top: float, text: str, color) -> None:
        """Glyph by glyph from the line box's (scaled) top-left."""
        renderer._blit_baked_line(self.font, text, left, top, color)


@dataclass(frozen=True)
class _FaceGlyphs:
    """A text's glyphs from a device typeface (`fallback.SystemFace`, already
    at the preview's scale): a system or vector font's own file or its
    stand-in, or a `.cft` bitmap font."""

    face: "fallback.SystemFace"

    @property
    def line_height(self) -> float:
        return self.face.line_height

    def width(self, text: str) -> float:
        return self.face.width(text)

    def draw(self, renderer: "Renderer", left: float, top: float, text: str, color) -> None:
        """Glyph by glyph on the face's own baseline, `face.baseline` below
        the line box's (scaled) top -- never Pillow's own vertical anchors,
        which measure the stand-in's ascender/descender and would disagree
        with the line height the metric defines."""
        renderer._draw_system_line(self.face, left, top + self.face.baseline, text, color)


class Renderer:
    """Draws one resolved face into a Pillow image for `wfb preview`, the
    way the generated code draws it on the watch.

    **Helpers for kind authors.**  A kind's `draw_preview` gets the
    renderer: `renderer.draw` is the `ImageDraw`, `renderer.scale` the
    upscale every device pixel is multiplied by, and `renderer.values` the
    sample readings.

    - Values: `color` (a colour expression to RGB) and `visible` (a
      `visible:` expression); `aod_color`, `aod_field` and `aod_geometry`
      apply the element's `aod:` override and `dim:` while `--aod`
      renders, the twins of `wfb.emit.monkeyc.common.AodStyle`.
    - Text: `draw_text` (upright, in a baked or system font),
      `draw_vector_text` (a `face:` font, upright or curved),
      `draw_outlined` (an `outline:` ring around either), `glyph_source`,
      `paste_glyph`.
    - Shapes: `rect` (a box in preview pixels), `hand_part` (one part of a
      hand or of a pattern copy).

    Module level: `baked_glyph`, `arc_span`.
    """

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

    def aod_field(self, element, key: str, base):
        """``base``, replaced by this element's resolved `aod:` override for
        ``key`` while `--aod` renders and one is set."""
        if not self.options.aod or element.aod is None:
            return base
        override = getattr(element.aod, key)
        return override if override is not None else base

    def aod_geometry(self, placed, key: str, base):
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

    def aod_color(self, element, key: str, base_expr,
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
        base = self.color(base_expr, values)
        if not self.options.aod or element.aod is None:
            return base
        choice, override = aod_color_choice(element.aod, key, self.resolved.face.aod_dim is not None)
        if choice == "override":
            return self.color(override)
        if choice == "dim":
            return self._dim_rgb(base)
        return base

    def aod_dimmed(self, element, expr, values: dict | None = None) -> tuple[int, int, int]:
        """``expr``'s RGB, dimmed while `--aod` renders an element the AOD
        frame draws and the face has `aod: {dim: ...}` -- the twin of
        `wfb.emit.monkeyc.common.AodStyle.dimmed`, for a colour no `aod:`
        override key reaches (an `outline:` ring carried over from the
        awake design, a pattern part's own ring)."""
        base = self.color(expr, values)
        if not self.options.aod or element.aod is None or self.resolved.face.aod_dim is None:
            return base
        return self._dim_rgb(base)

    # -- dispatch ---------------------------------------------------------

    def render_element(self, placed) -> None:
        # `--aod`: the fully resolved AOD gate (`element.visible` already
        # folded in), which an `aod: {visible: ...}` may narrow further.
        visible = (placed.element.aod.visible if self.options.aod and placed.element.aod
                   else placed.element.visible)
        if not self.visible(visible):
            return
        kinds.for_placed(placed).draw_preview(self, placed)

    # -- elements ---------------------------------------------------------

    def hand_part(self, placed: PlacedHands | PlacedPattern, part, cx: float, cy: float,
                  sin_t: float, cos_t: float, values: dict | None = None) -> None:
        """One polygon/line/circle part of a hand or pattern copy, its
        vertices rotated by `(sin_t, cos_t)` about the scaled `(cx, cy)`.
        The element-level `aod:` colour/thickness override applies to every
        part (`aod_color`, `aod_geometry`)."""
        s = self.scale
        fill = self.aod_color(placed.element, "color", part.color, values)

        def rotated(x: float, y: float) -> tuple[float, float]:
            return (cx + (x * cos_t - y * sin_t) * s, cy + (x * sin_t + y * cos_t) * s)

        if part.shape == "polygon":
            if len(part.points) >= 3:
                self.draw.polygon([rotated(x, y) for x, y in part.points], fill=fill)
        elif part.shape == "line":
            x1, y1 = rotated(part.x1, part.y1)
            x2, y2 = rotated(part.x2, part.y2)
            thickness = self.aod_geometry(placed, "thickness", part.thickness)
            self.draw.line([x1, y1, x2, y2], fill=fill, width=max(1, thickness * s))
        else:  # circle
            x, y = rotated(part.x, part.y)
            r = part.radius * s
            box = [x - r, y - r, x + r, y + r]
            if part.filled:
                self.draw.ellipse(box, fill=fill)
            else:
                thickness = self.aod_geometry(placed, "thickness", part.thickness)
                self.draw.ellipse(box, outline=fill, width=max(1, thickness * s))

    def draw_outlined(self, draw: Callable[..., None], anchor: tuple[int, int], color,
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

    # -- text helpers -----------------------------------------------------

    def glyph_source(self, font: BakedFont | None, metric: FontMetric | None):
        """Where a text's glyphs come from: `font`'s baked sheet, else the
        device typeface `metric` names (its real file, a stand-in, or a
        `.cft` bitmap font -- `_system_face`). `None` when there is neither
        a sheet nor a metric with a scalable face."""
        if font is not None and font.sheet is not None:
            return _BakedGlyphs(font, self.scale)
        if metric is None:
            return None
        face = self._system_face(metric, scale=self.scale)
        return _FaceGlyphs(face) if face is not None else None

    def draw_text(self, font: BakedFont | None, text: str, anchor: tuple[int, int],
                  align: str, vertical_align: str, metric: FontMetric | None,
                  color: tuple[int, int, int], box=None) -> None:
        """Draw `text` upright at `anchor`: place its line box by the shared
        alignment rule (`wfb.layout.alignment_shift`: `align`/
        `vertical_align` say which edge of the box sits on the anchor --
        the same top edge `PlacedText.box` and the lint box use), then draw
        glyph by glyph from its `glyph_source`. Shared by `text`, pattern
        text and upright vector text. With no glyph source (no pixel metrics
        for this symbol on this device, or no scalable face at all), `box`
        -- a `text` element's -- is outlined instead: more honest than text
        at the wrong size. A `substitute`/`none` face draws the watch's
        glyph *positions* exactly, since layout measured with it.
        """
        source = self.glyph_source(font, metric)
        if source is None:
            self._mark_extent(box)
            return
        s = self.scale
        width, line_height = source.width(text), source.line_height
        left = anchor[0] * s - {"left": 0, "right": width}.get(align, width / 2)
        top = anchor[1] * s - {"top": 0, "center": line_height / 2,
                               "bottom": line_height}[vertical_align]
        source.draw(self, left, top, text, color)

    def _blit_baked_line(self, font: BakedFont, text: str, left: float, top: float,
                         color: tuple[int, int, int]) -> None:
        """Paste `text`'s baked glyphs pen-wise from the (already scaled)
        top-left of their line box, skipping any glyph the sheet lacks."""
        pen = left
        for char in text:
            glyph = font.glyphs.get(char)
            if glyph is None:
                continue
            self.paste_glyph(font.sheet, glyph, pen, top, color)
            pen += glyph.xadvance * self.scale

    def paste_glyph(self, sheet: Image.Image, glyph, x: float, y: float,
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

    def draw_vector_text(
        self, text: str, anchor_point: tuple[int, int], align: str, vertical_align: str,
        font_metric, color, curve_style: str | None, curve_angle_garmin: float,
        curve_radius_px: int, curve_direction: str | None, *, box=None,
    ) -> None:
        """A `face:` (vector) font's draw -- upright (`curve_style is None`,
        exactly like a system font, `draw_text`), `angled`
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
            # Delegates to `draw_text` wholesale, including its "no scalable
            # face at all" fallback (an outline box, `box=box`) -- that edge
            # case is exactly as reachable, and exactly as handled, for a
            # vector font as for a system one.
            self.draw_text(None, text, anchor_point, align, vertical_align,
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
        size -- `draw_text`'s fallback when it has no glyph source.

        An empty box draws nothing. Unmeasured text gets exactly that: with
        no metric, layout has no extent to give it and records a 0x0 box at
        the anchor (every system font on a device missing from the scraped
        SDK reference, e.g. the fenix 9 family), and `rect` turns a 0-wide
        box into an inverted rectangle that Pillow rejects outright.
        """
        if box is None or box.width <= 0 or box.height <= 0:
            return
        self.draw.rectangle(self.rect(box), outline=(64, 64, 64), width=1)

    def rect(self, box) -> list[float]:
        """`box` scaled to preview pixels, as the `[x0, y0, x1, y1]` Pillow's
        `rectangle`/`ellipse`/`arc` take.
        """
        s = self.scale
        return [box.x * s, box.y * s, box.right * s - 1, box.bottom * s - 1]

    def visible(self, expression, values: dict | None = None) -> bool:
        """`visible:` -- the same rule the device runs, on the sample
        readings (`self.values`, or a pattern part's own `values` with
        `copy` bound to the copy being drawn -- `values` overrides
        `self.values` the same way `color`'s does).

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

    def color(self, expression, values: dict | None = None) -> tuple[int, int, int]:
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


def baked_glyph(font: BakedFont | None, char: str | None):
    """`char`'s `GlyphBox` in `font`, or `None` when there is no font, no
    sheet to crop from, or no such glyph -- the one "can this baked glyph
    be drawn" check `wfb.kinds.icon.IconKind.draw_preview` and
    `wfb.kinds.complication_slot.ComplicationSlotKind.draw_preview` share."""
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
