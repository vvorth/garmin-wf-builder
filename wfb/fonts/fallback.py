"""Turn a device `FONT_*` symbol's :class:`wfb.devices.FontMetric` into a
real, measurable face -- for both :mod:`wfb.layout` (measuring) and
:mod:`wfb.preview` (drawing), so the two can never disagree (the same reason
`wfb.layout` hands the preview its own resolved geometry rather than laying
out a second time, ADR 0004).

Custom fonts are baked from a real TrueType source, so their metrics are
exact.  **System fonts are estimated**, but no longer against Pillow's bundled
default face: `wfb/fonts/fetch_system.py` resolves the device's own font
*name* (``RobotoCondensed-Bold``, ``Bionic_semibold``, a bitmap ``FNT_*``
token, ...) to a real file -- the user's own Garmin font root when present, a
pinned free stand-in otherwise (`docs/research/10-system-fonts.md`'s mapping),
downloaded and cached on demand -- and this module measures and draws with
*that* face, scaled to the device's own published metrics rather than to a
flat per-character coefficient. It is still an estimate: per-glyph advances,
hinting and kerning of the real device font can differ from even an `exact`
match's free release, and a `substitute`/`none` match draws a different
family's shape entirely. Every diagnostic derived from it stays labelled as
such (`wfb.lint.check_text_fit`).

**A located Garmin file may be a `.cft` bitmap container instead of a
scalable `.ttf`/`.otf`** (decoded by :mod:`wfb.fonts.cft`) -- true for 8
of the 13 installed
devices, every one of which resolves *every* `FONT_*` symbol to a bitmap
file. :func:`system_face` tells the two apart by the located path's own
suffix and returns a :class:`SystemFace` either way, but a bitmap face's
`font` (the Pillow `FreeTypeFont` field) is `None`: there is no scalable
face to hand Pillow's own text-drawing calls, only per-glyph pixel cells
(`SystemFace.bitmap`, a decoded :class:`wfb.fonts.cft.CftFont`). **Every
consumer of `SystemFace.font` must handle `None`** -- `wfb.preview` is the
only one, and its bitmap branch pastes each glyph's own cell instead of
calling `ImageDraw.text`. A bitmap face's `line_height`/`baseline` come
from the `.cft` file's own `height`/`ascent` (scaled), which **override**
the metric's scraped `size_px` once such a file is actually found (plan 10
§2.3: it is the very file the simulator loads, so it outranks the
estimate) -- both :func:`system_face` and :func:`line_height` below apply
this override the same way, so layout and preview cannot disagree about a
bitmap face's line box either.

**The metric model** (verified in `docs/research/10-system-fonts.md` §3,
plan 09 §2/§4 R2): a device's `FontMetric` carries `size_px` (the published
*line height* -- always present when the device has an entry for the symbol
at all, and the number layout keeps using so nothing shifts where no better
data exists) and, when the installed device's own `simulator.json` states
them, `em_px` (`size_pt * ppi / 72`), `ascent_px` and `height_px`. Whatever
the metric does not carry is derived here from the located TTF's own `hhea`/
`head` tables (`_hhea`, a local `fontTools` import so `wfb.devices` itself
never needs Pillow/fontTools -- the same "no filesystem/library dependency
beyond what the caller actually asked for" shape `wfb/icons.py` and
`wfb/fonts/bmfont.py` already follow):

* `em_px` (the Pillow point size to load the face at) = `size_px * upm /
  (hhea_ascent - hhea_descent)` when the metric does not already give one.
* the line box height stays `metric.height_px` if given, else `metric.
  size_px` -- never re-derived from the TTF, since the device's own
  published line height is definitionally correct and the em/hhea model is
  only an estimate of it.
* the baseline, measured down from the line box's own top, is `metric.
  ascent_px` if given, else `round(em * hhea_ascent / upm)`.

:func:`system_face` is the one place all of this happens -- it returns a
:class:`SystemFace` (the loaded Pillow face, the line height, the baseline
and the match level `wfb.fonts.fetch_system.locate` reported), scaled by an
optional `scale` (the preview's own upscaling factor; `wfb.layout` always
measures at `scale=1`, the device's real pixel grid). `measure`/`line_height`
stay as the two entry points `wfb.layout` already called before this module
was rewritten, now taking a `FontMetric` instead of a bare pixel height.
`font_for_height` is unchanged and kept for its one remaining caller, the
style-sheet caption (`wfb.preview.render_all_styles`), which has no device
font to look up at all -- just a pixel height to fit a caption bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

from ..devices import FontMetric
from . import cft, fetch_system

#: Nominal em size used to probe Pillow's bundled default face's height ratio
#: (:func:`font_for_height` only -- the style-sheet caption).
_PROBE = 100

#: Used only when even a Pillow face is unavailable (older Pillow with no
#: scalable default, and no TTF could be located either).  A flat
#: coefficient per character -- the crude estimate this module exists to
#: improve on.
CRUDE_WIDTH_RATIO = 0.55


@dataclass(frozen=True)
class SystemFace:
    """A system font, ready to measure and draw with.

    `line_height`/`baseline` are already scaled by whatever `scale`
    :func:`system_face` was asked for, in the same pixel units as `font`
    itself -- a caller never has to re-derive either from the metric.

    **Two kinds, told apart by `bitmap`**: an outline
    face has `bitmap is None` and a real Pillow
    `FreeTypeFont` in `font`; a bitmap face (a located `.cft`) has
    `bitmap` set to its decoded `wfb.fonts.cft.CftFont` and **`font is
    None`** -- there is no scalable face to hand Pillow's text-drawing
    calls, only per-glyph pixel cells. Every consumer of `.font` must
    check `bitmap`/`None` first; `wfb.preview` is the only one, and its
    bitmap branch pastes each glyph's own cell instead.
    """

    font: ImageFont.FreeTypeFont | None
    #: The line box's own height, top to bottom.
    line_height: int
    #: Where the baseline sits, measured down from the line box's top --
    #: `wfb.preview` draws at `top + baseline` with a Pillow baseline anchor
    #: (`"ls"`/`"ms"`/`"rs"`), never at the box's own top or middle directly.
    baseline: int
    #: `"garmin"` | `"exact"` | `"family"` | `"substitute"` | `"none"` --
    #: `wfb.fonts.fetch_system.locate`'s own match level, carried through so
    #: a lint or a probe can report it.
    match: str
    #: The located file, when there is one -- a `.ttf`/`.otf` (what
    #: `advances` reads the font's own `hmtx` from) or, when `bitmap` is
    #: set, the `.cft`'s own path (kept here too so both kinds share one
    #: "where did this face come from" field). `None` for the Pillow-default
    #: stand-in.
    path: str | None = None
    #: The whole-pixel em the device lays glyphs out at (`round(em_px)`),
    #: and the preview's upscaling factor -- see `advances`. Unused (stays
    #: `None`) for a bitmap face: a `.cft` glyph's advance is already a
    #: whole pixel count, needing no em to scale against.
    layout_em: int | None = None
    scale: float = 1.0
    #: The decoded bitmap font behind this face, or `None` for an outline
    #: one -- see the class docstring. Set only by :func:`system_face`'s own
    #: `.cft` branch.
    bitmap: "cft.CftFont | None" = None

    def advances(self, text: str) -> list[float]:
        """Each character's advance, in this face's (scaled) pixels.

        **Bitmap** (`bitmap` set): each glyph's own `.cft` pen advance,
        times `scale` -- a whole-pixel count already, no em involved.

        **Outline**, the device model VERIFIED against the metrics probe
        (`docs/research/probes/system-font-metrics/`, 2026-09-18): every
        glyph advances by its `hmtx` width at the *whole-pixel* em,
        rounded to a whole device pixel on its own, no kerning --
        `round(adv * round(em_px) / upm)`. That reproduces all 36 Roboto
        width readings on the three targets exactly; Pillow's own
        `getlength` (fractional em, hinted) missed 21 of 54, TINY digits
        by a whole pixel each. Bionic is still off by up to 4 px over ten
        digits (Garmin's own rasteriser, not reproducible here).
        """
        if self.bitmap is not None:
            return [advance * self.scale for advance in self.bitmap.advances(text)]
        if self.path is None or self.layout_em is None:
            return [self.font.getlength(ch) for ch in text]
        table = _hmtx(self.path)
        if table is None:
            return [self.font.getlength(ch) for ch in text]
        cmap, widths, upm = table
        out = []
        for ch in text:
            glyph = cmap.get(ord(ch), ".notdef")
            width = widths.get(glyph, widths.get(".notdef", 0))
            out.append(round(width * self.layout_em / upm) * self.scale)
        return out

    def width(self, text: str) -> float:
        """`sum(advances(text))` -- the line's advance width."""
        return sum(self.advances(text))


@lru_cache(maxsize=64)
def _hhea(path: str) -> tuple[int, int, int] | None:
    """``(unitsPerEm, hhea.ascent, hhea.descent)`` of the TTF at ``path``, or
    `None` if it cannot be read (not a real TrueType/OpenType file, or
    missing a table this needs) -- never raises. `hhea.descent` is kept
    signed (negative) exactly as it sits in the font, matching plan 09 §2's
    own convention (`tools/research/font_metric_check.py`'s `load_hhea`,
    which this mirrors for the same reason: `wfb.devices` must not import
    `fontTools`, so the read happens here, lazily, once per distinct path).
    """
    try:
        from fontTools.ttLib import TTFont  # local import: only needed here

        font = TTFont(path, lazy=True, fontNumber=0)
        upm = font["head"].unitsPerEm
        hhea = font["hhea"]
        return int(upm), int(hhea.ascent), int(hhea.descent)
    except Exception:
        return None


@lru_cache(maxsize=64)
def _hmtx(path: str) -> tuple[dict[int, str], dict[str, int], int] | None:
    """``(cmap, advance widths by glyph name, unitsPerEm)`` of the TTF at
    ``path`` -- what `SystemFace.advances` lays a line out with. Never
    raises; `None` when the file cannot be read."""
    try:
        from fontTools.ttLib import TTFont  # local import: only needed here

        font = TTFont(path, lazy=True, fontNumber=0)
        widths = {name: adv for name, (adv, _lsb) in font["hmtx"].metrics.items()}
        return dict(font.getBestCmap() or {}), widths, int(font["head"].unitsPerEm)
    except Exception:
        return None


def _truetype(path: str, size: float) -> ImageFont.FreeTypeFont | None:
    """`ImageFont.truetype(path, size)`, accepting a float `size` when the
    installed Pillow supports it (the exact em, preferred) and falling back
    to the nearest whole point otherwise -- older Pillow releases require an
    `int`. Detected by trying, not by parsing `PIL.__version__`, so this
    keeps working across whatever Pillow point actually changed this (the
    change is not documented by a version this module could cite with
    confidence). Never raises: a corrupt or unreadable file also returns
    `None`, the same as an unsupported size would.
    """
    try:
        return ImageFont.truetype(path, size)
    except TypeError:
        return ImageFont.truetype(path, max(1, round(size)))
    except OSError:
        return None


@lru_cache(maxsize=64)
def _pillow_default(pixel_height: int) -> ImageFont.FreeTypeFont | None:
    """Pillow's bundled default face, scaled so its own
    `ascent + descent` is as close as possible to `pixel_height` -- the
    face `system_face` falls back to when `wfb.fonts.fetch_system.locate`
    finds nothing at all (match `"none"`), and `font_for_height`'s own
    implementation (kept separate so a change to one's caching/rounding
    cannot silently move the other's caption use)."""
    if pixel_height <= 0:
        return None
    try:
        probe = ImageFont.load_default(size=_PROBE)
        ascent, descent = probe.getmetrics()
        natural = ascent + descent
        if natural <= 0:
            return None
        size = max(6, round(_PROBE * pixel_height / natural))
        return ImageFont.load_default(size=size)
    except Exception:
        # Pillow older than 10.1 has no scalable default; callers fall back
        # to the crude estimate rather than failing a build over a preview
        # detail.
        return None


@lru_cache(maxsize=64)
def font_for_height(pixel_height: int) -> ImageFont.FreeTypeFont | None:
    """A font whose line height is as close as possible to ``pixel_height``.

    Unchanged from before this module was rewritten, and kept for its one
    remaining caller: `wfb.preview.render_all_styles`'s caption bar, which
    has no `FONT_*` symbol or device to look up -- only a pixel height to
    fit text into.
    """
    return _pillow_default(pixel_height)


@lru_cache(maxsize=256)
def system_face(metric: FontMetric, scale: float = 1.0, *,
                fonts_root: str | None = None) -> SystemFace | None:
    """The one place a :class:`wfb.devices.FontMetric` becomes a real,
    measurable Pillow face -- see the module docstring for the metric model.

    `scale` multiplies the em, line height and baseline together (the
    preview's own upscaling factor; `wfb.layout` always measures at
    `scale=1`, the device's real pixel grid), so a caller never has to
    re-derive one from the other -- the one reason a monkeypatched `em_px`
    (or this `scale`) moves both the layout width and the preview ink the
    same way, by construction. `lru_cache`d on `(metric, scale, fonts_root)`
    -- `FontMetric` is a frozen, hashable dataclass built exactly for this.

    Returns `None` only when even Pillow's own bundled default face cannot
    be loaded (older Pillow with no scalable default) -- a metric with no
    real font located at all (`fetch_system.locate` returning `(None,
    "none")`) still gets a `SystemFace`, built from that default face,
    scaled the same way a real one would be; `.match` is `"none"` in that
    case, which `wfb.lint`/a probe can report but is otherwise drawn
    exactly like any other match level (today's behaviour, kept).

    **A `.cft` bitmap hit is a separate branch**:
    `line_height_px`/`baseline_px` below
    are the *scraped/simulator* numbers, used for every outline face and
    the Pillow fallback, but a located `.cft`'s own `height`/`ascent`
    override them once the file is actually decoded (plan 10 §2.3 -- it is
    the very file the simulator loads, so it outranks the estimate). If the
    `.cft` fails to decode (corrupt/truncated), this falls back to the
    Pillow default the same way a missing/unreadable TTF would, rather than
    silently drawing at the wrong size.
    """
    if metric.size_px <= 0:
        return None

    line_height_px = metric.height_px if metric.height_px is not None else metric.size_px

    def _pillow_fallback(reported_match: str) -> SystemFace | None:
        face = _pillow_default(round(metric.size_px * scale))
        if face is None:
            return None
        ascent, descent = face.getmetrics()
        baseline = round((ascent / max(1, ascent + descent)) * line_height_px * scale)
        return SystemFace(
            font=face, line_height=round(line_height_px * scale),
            baseline=baseline, match=reported_match,
        )

    path, match = fetch_system.locate(metric.font, metric.face or None,
                                      fonts_root=fonts_root)
    if path is None:
        return _pillow_fallback("none")

    if str(path).lower().endswith(".cft"):
        bitmap_font = cft.load(path)
        if bitmap_font is None:
            return _pillow_fallback(match)
        return SystemFace(
            font=None,
            line_height=round(bitmap_font.height * scale),
            baseline=round(bitmap_font.ascent * scale),
            match=match,
            path=str(path),
            scale=scale,
            bitmap=bitmap_font,
        )

    hhea = _hhea(str(path))
    if hhea is None:
        return _pillow_fallback(match)

    upm, hhea_ascent, hhea_descent = hhea
    em = metric.em_px
    if em is None:
        ratio = (hhea_ascent - hhea_descent) / upm
        em = metric.size_px / ratio if ratio else float(metric.size_px)

    face = _truetype(str(path), em * scale)
    if face is None:
        return _pillow_fallback(match)

    baseline_px = metric.ascent_px if metric.ascent_px is not None else round(em * hhea_ascent / upm)
    return SystemFace(
        font=face,
        line_height=round(line_height_px * scale),
        baseline=round(baseline_px * scale),
        match=match,
        path=str(path),
        layout_em=max(1, round(em)),
        scale=scale,
    )


def measure(text: str, metric: FontMetric) -> tuple[int, bool]:
    """Estimate the pixel width of ``text`` at ``metric``'s size.

    Returns ``(width, from_real_metrics)``.  ``from_real_metrics`` is
    ``False`` only when no Pillow face at all was available (the crude
    flat-coefficient path) -- a `"none"`-match Pillow default and a real
    located device face both count as `True`, since both measure per
    character rather than assuming a flat width.
    """
    if not text:
        return 0, True
    face = system_face(metric)
    if face is None:
        return round(len(text) * metric.size_px * CRUDE_WIDTH_RATIO), False
    return round(face.width(text)), True


def line_height(metric: FontMetric) -> int:
    """The line box height `wfb.layout` measures with.

    Consults `system_face` (cached, so this costs nothing beyond the first
    call for a given metric) so that a located `.cft`'s own `height`
    overrides the scraped/simulator estimate exactly the way
    `system_face`'s own `SystemFace.line_height` does (plan 10
    §2.3/§3 B.3) -- `wfb.layout` and `wfb.preview`
    would otherwise disagree about a bitmap face's line box by the 0-2 px
    plan §2.3 found between `size_px` and the real file's `height`. Falls
    back to `metric.height_px` when the device states one, else
    `metric.size_px` (the published line height), for every other case --
    an outline face, no located file at all, or (defensively) a `.cft`
    that fails to decode.
    """
    face = system_face(metric)
    if face is not None and face.bitmap is not None:
        return face.line_height
    return metric.height_px if metric.height_px is not None else metric.size_px


def ascent(metric: FontMetric) -> int:
    """The baseline's distance below the line box's top -- the stand-in for
    `Graphics.getFontAscent` that `wfb.layout` measures radial text with
    (`radial_text_band`), read from the same cached `system_face` the
    preview draws with, so the lint band and the preview's own baseline
    agree by construction. Falls back to `metric.ascent_px` when stated,
    else the full line height (the whole box above the baseline -- the
    conservative end for a band built on it).
    """
    face = system_face(metric)
    if face is not None:
        return face.baseline
    if metric.ascent_px is not None:
        return metric.ascent_px
    return line_height(metric)
